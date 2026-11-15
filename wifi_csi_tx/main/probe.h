#pragma once
#include <stdint.h>
#define PROBE_SIZE 16
/* Explicit little endian; no dependence on structure padding. */
static inline void probe_encode(uint8_t out[PROBE_SIZE], uint32_t seq, uint64_t local_us)
{
    out[0] = 'C'; out[1] = 'S'; out[2] = 'I'; out[3] = 'P';
    for (unsigned i = 0; i < 4; ++i) out[4 + i] = (uint8_t)(seq >> (8 * i));
    for (unsigned i = 0; i < 8; ++i) out[8 + i] = (uint8_t)(local_us >> (8 * i));
}
