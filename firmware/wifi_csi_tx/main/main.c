#include <stdbool.h>
#include <inttypes.h>
#include <string.h>
#include "sdkconfig.h"
#include "esp_event.h"
#include "esp_idf_version.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_now.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "nvs_flash.h"
#include "probe.h"

#if ESP_IDF_VERSION != ESP_IDF_VERSION_VAL(6, 0, 2)
#error "This project targets ESP-IDF v6.0.2"
#endif
#if !CONFIG_IDF_TARGET_ESP32S3
#error "This project targets ESP32-S3"
#endif

#define READY BIT0
static const char *TAG = "csi_tx";
static const uint8_t broadcast[6] = {255, 255, 255, 255, 255, 255};
static EventGroupHandle_t events;
static SemaphoreHandle_t tx_available;
static portMUX_TYPE stats_lock = portMUX_INITIALIZER_UNLOCKED;
static uint32_t mac_fail;

static void wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    (void)data;
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        ESP_ERROR_CHECK(esp_wifi_connect());
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        xEventGroupClearBits(events, READY);
        ESP_LOGW(TAG, "Wi-Fi disconnected; reconnecting, probes paused");
        ESP_ERROR_CHECK(esp_wifi_connect());
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        uint8_t channel;
        wifi_second_chan_t secondary;
        ESP_ERROR_CHECK(esp_wifi_get_channel(&channel, &secondary));
        if (channel != CONFIG_APP_WIFI_CHANNEL) {
            xEventGroupClearBits(events, READY);
            ESP_LOGE(TAG, "Router channel=%u, expected=%d; probes paused",
                     channel, CONFIG_APP_WIFI_CHANNEL);
            return;
        }
        ESP_LOGI(TAG, "Router channel=%u, TX interval=%d ms",
                 channel, CONFIG_APP_TX_INTERVAL_MS);
        xEventGroupSetBits(events, READY);
    }
}

static void wifi_sta_start(void)
{
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    ESP_ERROR_CHECK(esp_netif_create_default_wifi_sta() ? ESP_OK : ESP_ERR_NO_MEM);
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event, NULL));
    wifi_config_t config = {0};
    const char *ssid = CONFIG_APP_WIFI_SSID;
    const char *password = CONFIG_APP_WIFI_PASSWORD;
    if (!strlen(ssid) || strlen(ssid) > sizeof(config.sta.ssid) ||
        strlen(password) > sizeof(config.sta.password)) {
        ESP_LOGE(TAG, "Invalid Wi-Fi configuration; configure CSI probe transmitter in menuconfig");
        ESP_ERROR_CHECK(ESP_ERR_INVALID_ARG);
    }
    memcpy(config.sta.ssid, ssid, strlen(ssid));
    memcpy(config.sta.password, password, strlen(password));
    config.sta.channel = CONFIG_APP_WIFI_CHANNEL;
    config.sta.threshold.authmode = strlen(password) ? WIFI_AUTH_WPA2_PSK : WIFI_AUTH_OPEN;
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &config));
    ESP_ERROR_CHECK(esp_wifi_set_protocol(WIFI_IF_STA, WIFI_PROTOCOL_11B | WIFI_PROTOCOL_11G | WIFI_PROTOCOL_11N));
    ESP_ERROR_CHECK(esp_wifi_set_bandwidth(WIFI_IF_STA, WIFI_BW20));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
    uint8_t mac[6];
    ESP_ERROR_CHECK(esp_wifi_get_mac(WIFI_IF_STA, mac));
    ESP_LOGI(TAG, "IMPORTANT TX STA MAC = " MACSTR, MAC2STR(mac));
}

static void espnow_send_cb(const esp_now_send_info_t *info, esp_now_send_status_t status)
{
    (void)info;
    if (status != ESP_NOW_SEND_SUCCESS) {
        portENTER_CRITICAL(&stats_lock);
        ++mac_fail;
        portEXIT_CRITICAL(&stats_lock);
    }
    xSemaphoreGive(tx_available);
}

static void tx_loop(void)
{
    uint32_t seq = 0, submitted = 0, errors = 0, skipped = 0;
    const TickType_t period = pdMS_TO_TICKS(CONFIG_APP_TX_INTERVAL_MS);
    configASSERT(period > 0);
    TickType_t next = xTaskGetTickCount();
    int64_t last_log = esp_timer_get_time();
    for (;;) {
        uint8_t channel;
        wifi_second_chan_t secondary;
        bool ready = (xEventGroupGetBits(events) & READY) != 0;
        if (ready && esp_wifi_get_channel(&channel, &secondary) == ESP_OK &&
            channel == CONFIG_APP_WIFI_CHANNEL && xSemaphoreTake(tx_available, 0) == pdTRUE) {
            uint8_t payload[PROBE_SIZE];
            probe_encode(payload, seq++, (uint64_t)esp_timer_get_time());
            esp_err_t err = esp_now_send(broadcast, payload, sizeof(payload));
            if (err == ESP_OK) {
                ++submitted;
            } else {
                ++errors;
                xSemaphoreGive(tx_available);
                if (errors == 1 || errors % 100 == 0) {
                    ESP_LOGW(TAG, "esp_now_send: %s", esp_err_to_name(err));
                }
            }
        } else {
            ++skipped;
        }
        int64_t now = esp_timer_get_time();
        if (now - last_log >= 10000000) {
            portENTER_CRITICAL(&stats_lock);
            uint32_t failures = mac_fail;
            portEXIT_CRITICAL(&stats_lock);
            ESP_LOGI(TAG, "ESP-NOW submitted=%" PRIu32 " errors=%" PRIu32
                     " mac_fail=%" PRIu32 " skipped=%" PRIu32,
                     submitted, errors, failures, skipped);
            last_log = now;
        }
        /* Do not flood the radio with catch-up packets after a missed deadline. */
        if (xTaskDelayUntil(&next, period) == pdFALSE) {
            vTaskDelay(period);
            next = xTaskGetTickCount();
        }
    }
}

void app_main(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);
    events = xEventGroupCreate();
    tx_available = xSemaphoreCreateBinary();
    ESP_ERROR_CHECK(events && tx_available ? ESP_OK : ESP_ERR_NO_MEM);
    xSemaphoreGive(tx_available);
    wifi_sta_start();
    ESP_ERROR_CHECK(esp_now_init());
    ESP_ERROR_CHECK(esp_now_register_send_cb(espnow_send_cb));
    esp_now_peer_info_t peer = {.channel = CONFIG_APP_WIFI_CHANNEL, .ifidx = WIFI_IF_STA};
    memcpy(peer.peer_addr, broadcast, sizeof(broadcast));
    ESP_ERROR_CHECK(esp_now_add_peer(&peer));
    esp_now_rate_config_t rate = {.phymode = WIFI_PHY_MODE_HT20, .rate = WIFI_PHY_RATE_MCS0_LGI};
    ESP_ERROR_CHECK(esp_now_set_peer_rate_config(broadcast, &rate));
    tx_loop();
}
