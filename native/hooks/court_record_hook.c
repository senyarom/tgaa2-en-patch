#include <stdint.h>
#include <stdbool.h>

struct symbol_info {
    uint8_t width_height; // 4 bits width, 4 bits height
    // Although height seems to be the same for all glyphs, 
    // I'll store it in case it's not true for some character.
};

/**
 * for (let i = 0; i < 95; i++) {
 *   console.log(`{ 0x }, // '${String.fromCharCode(i + 32)}'`);
 * }
 */
static const struct symbol_info symbol_map[95] = {
    { 0x3F }, // ' '
    { 0x5F }, // '!'
    { 0x6F }, // '"'
    { 0xAF }, // '#'
    { 0x8F }, // '$'
    { 0xBF }, // '%'
    { 0x9F }, // '&'
    { 0x3F }, // '''
    { 0x5F }, // '('
    { 0x5F }, // ')'
    { 0x6F }, // '*'
    { 0x9F }, // '+'
    { 0x4F }, // ','
    { 0x5F }, // '-'
    { 0x4F }, // '.'
    { 0x7F }, // '/'
    { 0x8F }, // '0'
    { 0x7F }, // '1'
    { 0x8F }, // '2'
    { 0x7F }, // '3'
    { 0x8F }, // '4'
    { 0x7F }, // '5'
    { 0x8F }, // '6'
    { 0x7F }, // '7'
    { 0x8F }, // '8'
    { 0x8F }, // '9'
    { 0x4F }, // ':'
    { 0x4F }, // ';'
    { 0x9F }, // '<'
    { 0x8F }, // '='
    { 0x9F }, // '>'
    { 0x7F }, // '?'
    { 0xBF }, // '@'
    { 0xAF }, // 'A'
    { 0x8F }, // 'B'
    { 0x9F }, // 'C'
    { 0xAF }, // 'D'
    { 0x8F }, // 'E'
    { 0x8F }, // 'F'
    { 0xAF }, // 'G'
    { 0xBF }, // 'H'
    { 0x5F }, // 'I'
    { 0x5F }, // 'J'
    { 0xAF }, // 'K'
    { 0x8F }, // 'L'
    { 0xCF }, // 'M'
    { 0xAF }, // 'N'
    { 0xAF }, // 'O'
    { 0x8F }, // 'P'
    { 0xAF }, // 'Q'
    { 0x9F }, // 'R'
    { 0x8F }, // 'S'
    { 0x8F }, // 'T'
    { 0xAF }, // 'U'
    { 0x9F }, // 'V'
    { 0xEF }, // 'W'
    { 0x9F }, // 'X'
    { 0x9F }, // 'Y'
    { 0x9F }, // 'Z'
    { 0x5F }, // '['
    { 0x7F }, // '\'
    { 0x5F }, // ']'
    { 0x8F }, // '^'
    { 0x7F }, // '_'
    { 0x6F }, // '`'
    { 0x7F }, // 'a'
    { 0x8F }, // 'b'
    { 0x7F }, // 'c'
    { 0x8F }, // 'd'
    { 0x7F }, // 'e'
    { 0x5F }, // 'f'
    { 0x8F }, // 'g'
    { 0x8F }, // 'h'
    { 0x4F }, // 'i'
    { 0x4F }, // 'j'
    { 0x8F }, // 'k'
    { 0x4F }, // 'l'
    { 0xDF }, // 'm'
    { 0x9F }, // 'n'
    { 0x8F }, // 'o'
    { 0x8F }, // 'p'
    { 0x8F }, // 'q'
    { 0x7F }, // 'r'
    { 0x6F }, // 's'
    { 0x6F }, // 't'
    { 0x8F }, // 'u'
    { 0x8F }, // 'v'
    { 0xBF }, // 'w'
    { 0x8F }, // 'x'
    { 0x8F }, // 'y'
    { 0x7F }, // 'z'
    { 0x5F }, // '{'
    { 0x4F }, // '|'
    { 0x5F }, // '}'
    { 0x9F }, // '~'
};

typedef void (*set_court_record_detail_fn)(
    void *detail,
    const char *name,
    const char *caption
);

#ifndef ORIGINAL_SET_COURT_RECORD_DETAIL
#error "ORIGINAL_SET_COURT_RECORD_DETAIL not set"
#endif

enum {
    COURT_RECORD_WIDTH = 208,
    COURT_RECORD_HEIGHT = 66,
    COURT_RECORD_MINIMUM_FONT_SIZE = 8,
    COURT_RECORD_CAPTION_CAPACITY = 256,
};

struct output_state {
    char *output;
    char *limit;
    uint16_t x;
    uint16_t used_height;
    uint16_t line_height;
    uint16_t font_size;
};

static bool starts_with(const char *str, const char *pref, uint16_t pref_len) {
    uint16_t i = 0;
    while (i < pref_len && str[i] != '\0') {
        if (str[i] != pref[i]) {
            return false;
        }
        i++;
    }
    return i == pref_len;
}

static uint16_t parse_size(const char **cursor) {
    const char *p = *cursor + 6; // Skip "<SIZE "
    uint16_t size = 0;

    while (*p >= '0' && *p <= '9') {
        size = size * 10 + (*p - '0');
        p++;
    }

    if (*p == '>') {
        *cursor = p + 1;
        return size;
    }

    return 0;
}

static bool is_space(char c) {
    return c == ' ' || c == '\t' || c == '\r' || c == '\n';
}

static bool append_char(struct output_state *state, char c) {
    if (state->output >= state->limit) {
        return false;
    }
    *state->output++ = c;
    return true;
}

static bool append_range(
    struct output_state *state,
    const char *begin,
    const char *end
) {
    while (begin < end) {
        if (!append_char(state, *begin++)) {
            return false;
        }
    }
    return true;
}

static bool append_uint(struct output_state *state, uint16_t value) {
    bool wrote_hundreds = false;
    if (value > 999) {
        return false;
    }
    if (value >= 100) {
        char digit = '0';
        while (value >= 100) {
            value -= 100;
            digit++;
        }
        if (!append_char(state, digit)) {
            return false;
        }
        wrote_hundreds = true;
    }
    if (value >= 10 || wrote_hundreds) {
        char digit = '0';
        while (value >= 10) {
            value -= 10;
            digit++;
        }
        if (!append_char(state, digit)) {
            return false;
        }
    }
    return append_char(state, (char)('0' + value));
}

static uint16_t scaled_width(uint16_t base_width, uint16_t font_size) {
    /* Exact unsigned division by 12 for the supported (<= 999) font sizes.
     * Keeping this division inline also avoids pulling __aeabi_idiv into the
     * compact Thumb build used by TGAA2's executable tail padding. */
    const uint32_t value = (uint32_t)base_width * font_size + 6;
    return (uint16_t)((value * 0xAAABu) >> 19);
}

static const char *next_glyph(
    const char *cursor,
    uint16_t font_size,
    uint16_t *width
) {
    const uint8_t first = (uint8_t)cursor[0];
    uint16_t base_width;
    uint8_t length;

    if (first >= ' ' && first <= '~') {
        base_width = symbol_map[first - ' '].width_height >> 4;
        length = 1;
    } else if (
        first == 0xE2 &&
        (uint8_t)cursor[1] == 0x80 &&
        (uint8_t)cursor[2] == 0x93
    ) {
        /* U+2013 EN DASH, the only non-ASCII Court Record character. */
        base_width = 7;
        length = 3;
    } else if ((first & 0xE0) == 0xC0) { /* 110xxxxx: 2 bytes */
        base_width = 14;
        length = 2;
    } else if ((first & 0xF0) == 0xE0) { /* 1110xxxx: 3 bytes */
        base_width = 14;
        length = 3;
    } else if ((first & 0xF8) == 0xF0) { /* 11110xxx: 4 bytes */
        base_width = 14;
        length = 4;
    } else {
        return 0;
    }

    for (uint8_t index = 1; index < length; index++) {
        if (cursor[index] == '\0' ||
            ((uint8_t)cursor[index] & 0xC0) != 0x80) {
            return 0;
        }
    }

    *width = scaled_width(base_width, font_size);
    return cursor + length;
}

static const char *tag_end(const char *cursor) {
    if (*cursor != '<') {
        return 0;
    }
    while (*cursor != '\0' && *cursor != '>') {
        cursor++;
    }
    return *cursor == '>' ? cursor + 1 : 0;
}

static bool measure_word(
    const char *begin,
    uint16_t font_size,
    const char **end,
    uint16_t *width
) {
    const char *cursor = begin;
    uint16_t result = 0;

    while (*cursor != '\0' && !is_space(*cursor)) {
        if (*cursor == '<') {
            cursor = tag_end(cursor);
            if (cursor == 0) {
                return false;
            }
            continue;
        }

        uint16_t glyph_width;
        const char *next = next_glyph(cursor, font_size, &glyph_width);
        if (next == 0) {
            return false;
        }
        result += glyph_width;
        cursor = next;
    }

    *end = cursor;
    *width = result;
    return true;
}

static bool emit_newline(struct output_state *state) {
    if (state->used_height + state->line_height > COURT_RECORD_HEIGHT) {
        return false;
    }
    if (!append_char(state, '\r') || !append_char(state, '\n')) {
        return false;
    }
    state->used_height += state->line_height;
    state->x = 0;
    return true;
}

static bool emit_long_word(
    struct output_state *state,
    const char *begin,
    const char *end
) {
    const char *cursor = begin;

    while (cursor < end) {
        if (*cursor == '<') {
            const char *after_tag = tag_end(cursor);
            if (after_tag == 0 || after_tag > end ||
                !append_range(state, cursor, after_tag)) {
                return false;
            }
            cursor = after_tag;
            continue;
        }

        uint16_t width;
        const char *next = next_glyph(cursor, state->font_size, &width);
        if (next == 0 || next > end) {
            return false;
        }
        if (state->x != 0 && state->x + width > COURT_RECORD_WIDTH &&
            !emit_newline(state)) {
            return false;
        }
        if (!append_range(state, cursor, next)) {
            return false;
        }
        state->x += width;
        cursor = next;
    }
    return true;
}

static bool reflow_caption_at_size(
    const char *body,
    char *result,
    uint16_t capacity,
    uint16_t font_size
) {
    static const char size_prefix[] = "<SIZE ";
    if (capacity == 0) {
        return false;
    }
    const uint16_t line_height = scaled_width(15, font_size);
    struct output_state state = {
        .output = result,
        .limit = result + capacity - 1,
        .x = 0,
        .used_height = line_height,
        .line_height = line_height,
        .font_size = font_size,
    };

    if (state.line_height > COURT_RECORD_HEIGHT ||
        !append_range(&state, size_prefix, size_prefix + 6) ||
        !append_uint(&state, font_size) ||
        !append_char(&state, '>')) {
        return false;
    }

    const char *cursor = body;
    while (*cursor != '\0') {
        while (is_space(*cursor)) {
            cursor++;
        }
        if (*cursor == '\0') {
            break;
        }

        const char *word_end;
        uint16_t word_width;
        if (!measure_word(cursor, font_size, &word_end, &word_width)) {
            return false;
        }

        if (word_width == 0) {
            if (!append_range(&state, cursor, word_end)) {
                return false;
            }
        } else if (word_width > COURT_RECORD_WIDTH) {
            if (state.x != 0 && !emit_newline(&state)) {
                return false;
            }
            if (!emit_long_word(&state, cursor, word_end)) {
                return false;
            }
        } else {
            const uint16_t space_width = scaled_width(3, font_size);
            if (state.x != 0 &&
                state.x + space_width + word_width > COURT_RECORD_WIDTH) {
                if (!emit_newline(&state)) {
                    return false;
                }
            } else if (state.x != 0) {
                if (!append_char(&state, ' ')) {
                    return false;
                }
                state.x += space_width;
            }

            if (!append_range(&state, cursor, word_end)) {
                return false;
            }
            state.x += word_width;
        }
        cursor = word_end;
    }

    *state.output = '\0';
    return true;
}

static bool reflow_caption(
    const char *caption,
    char *result,
    uint16_t capacity
) {
    if (caption == 0 || result == 0 || capacity == 0) {
        return false;
    }

    const char *body = caption;
    uint16_t original_size = 12; // Default size if not specified
    if (starts_with(caption, "<SIZE ", 6)) {
        original_size = parse_size(&body);
        if (original_size == 0 || original_size > 999) {
            original_size = 12; // Fallback to default size if parsing fails
        }
    }

    uint16_t minimum_size = original_size < COURT_RECORD_MINIMUM_FONT_SIZE
        ? original_size
        : COURT_RECORD_MINIMUM_FONT_SIZE;
    ;

    for (uint16_t size = original_size; size >= minimum_size; size--) {
        if (reflow_caption_at_size(body, result, capacity, size)) {
            return true;
        }
    }
    return false;
}

__attribute__((used, noinline, section(".text.court_record_hook")))
void court_record_detail_hook(
    void *detail,
    const char *name,
    const char *caption
) {
    const set_court_record_detail_fn original =
        (set_court_record_detail_fn)(uintptr_t)ORIGINAL_SET_COURT_RECORD_DETAIL;

    char wrapped[COURT_RECORD_CAPTION_CAPACITY];
    if (reflow_caption(caption, wrapped, sizeof(wrapped))) {
        original(detail, name, wrapped);
    } else {
        original(detail, name, caption);
    }
}
