#include <stdbool.h>
#include <stdint.h>

/* Native host builds do not understand the ARM/Mach-O section annotation. */
#define __attribute__(attributes)
#include "../native/hooks/court_record_hook.c"

bool court_record_host_reflow(
    const char *caption,
    char *result,
    uint16_t capacity
) {
    return reflow_caption(caption, result, capacity);
}
