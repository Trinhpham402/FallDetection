#include <inttypes.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include "sdkconfig.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_now.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "nvs_flash.h"
#include "lwip/sockets.h"
#include "protocol.h"

#if !CONFIG_IDF_TARGET_ESP32S3
#error "This receiver requires the esp32s3 target"
#endif
#if !CONFIG_ESP_WIFI_CSI_ENABLED
#error "Enable CONFIG_ESP_WIFI_CSI_ENABLED before building the receiver"
#endif

#define READY_BIT BIT0
static const char *TAG = "csi_rx";
static QueueHandle_t queue;
static EventGroupHandle_t network;
static uint8_t tx_mac[6];
static struct sockaddr_in server;
static portMUX_TYPE stats_lock = portMUX_INITIALIZER_UNLOCKED;
static uint32_t q_drop, invalid_csi, malformed_tx, offline_drop;
/* These are accessed only from the Wi-Fi task. */
static uint32_t csi_seq;
static int64_t last_csi_us;
typedef struct {
    uint16_t len;
    uint8_t bytes[CSI_HEADER_BYTES + CSI_MAX_BYTES];
} packet_t;

static void count(uint32_t *value)
{
    portENTER_CRITICAL(&stats_lock);
    ++*value;
    portEXIT_CRITICAL(&stats_lock);
}
static bool ready(void) { return (xEventGroupGetBits(network) & READY_BIT) != 0; }
static void enqueue(const packet_t *p)
{
    if (xQueueSend(queue, p, 0) != pdTRUE) count(&q_drop);
}
static void wifi_csi_cb(void *ctx, wifi_csi_info_t *info)
{
    (void)ctx;
    if (!info || memcmp(info->mac, tx_mac, 6)) return;
    if (!ready() || info->rx_ctrl.channel != CONFIG_APP_WIFI_CHANNEL) return;
    /* One HT-LTF, HT20 MCS0 long GI, no STBC/secondary channel. Never guess
       a subcarrier layout from the buffer length alone. */
    if (!info->buf || info->len != CSI_PROFILE_IQ_BYTES ||
        info->rx_ctrl.sig_mode != 1 || info->rx_ctrl.cwb != 0 ||
        info->rx_ctrl.mcs != 0 || info->rx_ctrl.stbc != 0 ||
        info->rx_ctrl.secondary_channel != 0 || info->rx_ctrl.sgi != 0 ||
        info->rx_ctrl.rx_state != 0) {
        count(&invalid_csi); return;
    }
    int64_t now = esp_timer_get_time();
    if (last_csi_us && now - last_csi_us < (int64_t)CONFIG_APP_MIN_CSI_INTERVAL_MS * 1000) return;
    last_csi_us = now;
    packet_t p = {0};
    p.len = encode_csi(p.bytes, CONFIG_APP_RX_NODE_ID, info->rx_ctrl.channel,
        info->rx_ctrl.rssi, info->rx_ctrl.noise_floor, info->first_word_invalid,
        csi_seq++, now, info->mac, info->buf, info->len,
        info->rx_ctrl.sig_mode, info->rx_ctrl.cwb, info->rx_ctrl.mcs,
        info->rx_ctrl.stbc, info->rx_ctrl.secondary_channel,
        info->rx_ctrl.sgi, info->rx_ctrl.timestamp);
    enqueue(&p);
}
static void esp_now_recv_cb(const esp_now_recv_info_t *info, const uint8_t *data, int len)
{
    if (!info || !info->src_addr || !info->rx_ctrl || memcmp(info->src_addr, tx_mac, 6)) return;
    if (!ready() || info->rx_ctrl->channel != CONFIG_APP_WIFI_CHANNEL) return;
    uint32_t seq; uint64_t tx_time;
    if (len < 0 || !parse_csip(data, (size_t)len, &seq, &tx_time)) {
        count(&malformed_tx); return;
    }
    packet_t p = {0};
    p.len = encode_tx(p.bytes, CONFIG_APP_RX_NODE_ID, info->rx_ctrl->channel,
        info->rx_ctrl->rssi, seq, tx_time, esp_timer_get_time(), info->src_addr);
    enqueue(&p);
}
static void wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        ESP_ERROR_CHECK(esp_wifi_connect());
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        const wifi_event_sta_disconnected_t *event = data;
        xEventGroupClearBits(network, READY_BIT);
        if (event) {
            ESP_LOGW(TAG, "Disconnected: reason=%u rssi=%d; reconnecting",
                (unsigned)event->reason, (int)event->rssi);
        } else {
            ESP_LOGW(TAG, "Disconnected: no event data; reconnecting");
        }
        esp_err_t err = esp_wifi_connect();
        if (err != ESP_OK) ESP_LOGE(TAG, "Reconnect: %s", esp_err_to_name(err));
    } else if (base == IP_EVENT && id == IP_EVENT_STA_LOST_IP) {
        xEventGroupClearBits(network, READY_BIT);
        ESP_LOGW(TAG, "Lost IP; capture disabled until Wi-Fi is ready again");
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        const ip_event_got_ip_t *event = data;
        if (event) ESP_LOGI(TAG, "Got IP: " IPSTR, IP2STR(&event->ip_info.ip));
        uint8_t primary; wifi_second_chan_t secondary;
        ESP_ERROR_CHECK(esp_wifi_get_channel(&primary, &secondary));
        if (primary != CONFIG_APP_WIFI_CHANNEL) {
            xEventGroupClearBits(network, READY_BIT);
            ESP_LOGE(TAG, "AP channel %u != configured %u; capture disabled", primary, CONFIG_APP_WIFI_CHANNEL);
        } else {
            xEventGroupSetBits(network, READY_BIT);
            ESP_LOGI(TAG, "Wi-Fi ready on channel %u", primary);
        }
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
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, ESP_EVENT_ANY_ID, wifi_event, NULL));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    wifi_config_t cfg = {0};
    memcpy(cfg.sta.ssid, CONFIG_APP_WIFI_SSID, strlen(CONFIG_APP_WIFI_SSID));
    memcpy(cfg.sta.password, CONFIG_APP_WIFI_PASSWORD, strlen(CONFIG_APP_WIFI_PASSWORD));
    cfg.sta.channel = CONFIG_APP_WIFI_CHANNEL;
    cfg.sta.scan_method = WIFI_ALL_CHANNEL_SCAN;
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &cfg));
    ESP_ERROR_CHECK(esp_wifi_set_bandwidth(WIFI_IF_STA, WIFI_BW20));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
}
static void udp_worker(void *arg)
{
    (void)arg;
    int fd = -1;
    uint32_t sent = 0, send_fail = 0;
    int64_t last_log = esp_timer_get_time();
    packet_t p;
    for (;;) {
        if (xQueueReceive(queue, &p, pdMS_TO_TICKS(1000)) == pdTRUE) {
            if (!ready()) {
                count(&offline_drop);
            } else {
                if (fd < 0) {
                    fd = socket(AF_INET, SOCK_DGRAM, IPPROTO_IP);
                    if (fd >= 0) {
                        struct timeval timeout = {.tv_sec = 0, .tv_usec = 200000};
                        if (setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout)) < 0) {
                            close(fd); fd = -1;
                        }
                    }
                }
                if (fd < 0 || sendto(fd, p.bytes, p.len, 0, (struct sockaddr *)&server, sizeof(server)) != p.len) {
                    ++send_fail;
                    if (fd >= 0) close(fd);
                    fd = -1;
                    vTaskDelay(pdMS_TO_TICKS(100));
                } else ++sent;
            }
        }
        if (!ready() && fd >= 0) { close(fd); fd = -1; }
        int64_t now = esp_timer_get_time();
        if (now - last_log >= 5000000) {
            uint32_t dropped, bad_csi, bad_tx, offline;
            portENTER_CRITICAL(&stats_lock);
            dropped = q_drop; bad_csi = invalid_csi; bad_tx = malformed_tx; offline = offline_drop;
            portEXIT_CRITICAL(&stats_lock);
            ESP_LOGI(TAG, "sent=%"PRIu32" q_drop=%"PRIu32" send_fail=%"PRIu32
                " invalid_csi=%"PRIu32" malformed_tx=%"PRIu32" offline_drop=%"PRIu32,
                sent, dropped, send_fail, bad_csi, bad_tx, offline);
            last_log = now;
        }
    }
}
static bool validate_config(void)
{
    unsigned mac[6]; int end = 0;
    if (strlen(CONFIG_APP_WIFI_SSID) == 0 || strlen(CONFIG_APP_WIFI_SSID) > 32 ||
        strlen(CONFIG_APP_WIFI_PASSWORD) > 64) return false;
    if (strlen(CONFIG_APP_TX_MAC) != 17 || sscanf(CONFIG_APP_TX_MAC,
        "%2x:%2x:%2x:%2x:%2x:%2x%n", &mac[0], &mac[1], &mac[2], &mac[3], &mac[4], &mac[5], &end) != 6 || end != 17) return false;
    unsigned nonzero = 0;
    for (int i = 0; i < 6; ++i) { tx_mac[i] = mac[i]; nonzero |= mac[i]; }
    if (!nonzero || (tx_mac[0] & 1)) return false;
    server.sin_family = AF_INET;
    server.sin_port = htons(CONFIG_APP_SERVER_PORT);
    if (inet_pton(AF_INET, CONFIG_APP_SERVER_IP, &server.sin_addr) != 1) return false;
    uint32_t ip = ntohl(server.sin_addr.s_addr);
    return ip != 0 && (ip >> 24) != 127 && (ip >> 24) < 224;
}
void app_main(void)
{
    if (!validate_config()) {
        ESP_LOGE(TAG, "Invalid RX configuration; set Wi-Fi, TX unicast MAC and server IPv4 in menuconfig");
        return;
    }
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase()); err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);
    network = xEventGroupCreate();
    queue = xQueueCreate(CONFIG_APP_QUEUE_DEPTH, sizeof(packet_t));
    ESP_ERROR_CHECK(network && queue ? ESP_OK : ESP_ERR_NO_MEM);
    ESP_ERROR_CHECK(xTaskCreate(udp_worker, "udp_worker", 4096, NULL, 4, NULL) == pdPASS ? ESP_OK : ESP_ERR_NO_MEM);
    wifi_sta_start();
    ESP_ERROR_CHECK(esp_now_init());
    ESP_ERROR_CHECK(esp_now_register_recv_cb(esp_now_recv_cb));
    wifi_promiscuous_filter_t filter = {.filter_mask = WIFI_PROMIS_FILTER_MASK_MGMT};
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous_filter(&filter));
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous(true));
    wifi_csi_config_t csi = {
        .lltf_en = false, .htltf_en = true, .stbc_htltf2_en = false,
        .ltf_merge_en = false, .channel_filter_en = false, .manu_scale = false, .shift = 0,
    };
    ESP_ERROR_CHECK(esp_wifi_set_csi_config(&csi));
    ESP_ERROR_CHECK(esp_wifi_set_csi_rx_cb(wifi_csi_cb, NULL));
    ESP_ERROR_CHECK(esp_wifi_set_csi(true));
    ESP_LOGI(TAG, "CSI profile=1 HT20/MCS0/LGI HT-LTF only, 128 raw bytes; host selects 52 data carriers");
    ESP_LOGI(TAG, "RX%d filter TX=%s -> %s:%d", CONFIG_APP_RX_NODE_ID,
        CONFIG_APP_TX_MAC, CONFIG_APP_SERVER_IP, CONFIG_APP_SERVER_PORT);
}
