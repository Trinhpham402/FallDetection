#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#define CSI_MAX_BYTES 512
#define CSI_HEADER_BYTES 40
#define CSI_PROFILE_HT20_DATA52 1
#define CSI_PROFILE_IQ_BYTES 128
#define TX_EVENT_BYTES 34
#define CSIP_BYTES 16

/* Explicit little-endian encoding: never send native structs over the wire. */
static inline void wire_put(uint8_t *p, uint64_t value, size_t bytes)
{
    for (size_t i = 0; i < bytes; ++i) p[i] = (uint8_t)(value >> (8 * i));
}
static inline uint64_t wire_get(const uint8_t *p, size_t bytes)
{
    uint64_t value = 0;
    for (size_t i = 0; i < bytes; ++i) value |= (uint64_t)p[i] << (8 * i);
    return value;
}
static inline bool parse_csip(const uint8_t *p, size_t len, uint32_t *seq, uint64_t *time)
{
    if (!p || len != CSIP_BYTES || memcmp(p, "CSIP", 4)) return false;
    *seq = (uint32_t)wire_get(p + 4, 4);
    *time = wire_get(p + 8, 8);
    return true;
}
static inline size_t encode_csi(uint8_t *out, uint8_t node, uint8_t channel,
    int8_t rssi, int8_t noise, bool first_invalid, uint32_t seq, uint64_t time,
    const uint8_t mac[6], const int8_t *iq, uint16_t len, uint8_t sig_mode,
    uint8_t cwb, uint8_t mcs, uint8_t stbc, uint8_t secondary, uint8_t sgi,
    uint32_t hw_time)
{
    if (!iq || !len || len > CSI_MAX_BYTES || (len & 1)) return 0;
    memset(out, 0, CSI_HEADER_BYTES);
    memcpy(out, "WCS2", 4);
    out[4] = node; out[5] = channel; out[6] = (uint8_t)rssi; out[7] = (uint8_t)noise;
    out[8] = first_invalid ? 1 : 0;
    out[9] = CSI_PROFILE_HT20_DATA52;
    wire_put(out + 10, len, 2); wire_put(out + 12, seq, 4); wire_put(out + 16, time, 8);
    memcpy(out + 24, mac, 6); memcpy(out + CSI_HEADER_BYTES, iq, len);
    out[30] = sig_mode; out[31] = cwb; out[32] = mcs; out[33] = stbc;
    out[34] = secondary; out[35] = sgi; wire_put(out + 36, hw_time, 4);
    return CSI_HEADER_BYTES + len;
}
static inline size_t encode_tx(uint8_t *out, uint8_t node, uint8_t channel,
    int8_t rssi, uint32_t seq, uint64_t tx_time, uint64_t rx_time, const uint8_t mac[6])
{
    memset(out, 0, TX_EVENT_BYTES); memcpy(out, "WTX1", 4);
    out[4] = node; out[5] = channel; out[6] = (uint8_t)rssi;
    wire_put(out + 8, seq, 4); wire_put(out + 12, tx_time, 8); wire_put(out + 20, rx_time, 8);
    memcpy(out + 28, mac, 6);
    return TX_EVENT_BYTES;
}
