#include <assert.h>
#include <stdio.h>
#include <string.h>

/* The ARM section annotation is not meaningful in a native host test. */
#define __attribute__(attributes)
#include "../native/hooks/court_record_hook.c"

static void test_known_caption(void) {
    static const char input[] =
        "<SIZE 14>Time of death just after 2 p.m. Death\r\n"
        "is believed to be due to trauma to the\r\n"
        "victim's lung from a knife blade. Only\r\n"
        "a single wound was identified.";
    static const char expected[] =
        "<SIZE 10>Time of death just after 2 p.m. Death\r\n"
        "is believed to be due to trauma to the\r\n"
        "victim's lung from a knife blade. Only\r\n"
        "a single wound was identified.";
    char output[COURT_RECORD_CAPTION_CAPACITY];

    assert(reflow_caption(input, output, sizeof(output)));
    assert(strcmp(output, expected) == 0);
}

static void test_long_word_is_split(void) {
    static const char input[] =
        "<SIZE 14>ABCDEFGHIJKLMNOPQRSTUVWXYZABCDEFGHIJKLMNOPQRSTUVWXYZ";
    char output[COURT_RECORD_CAPTION_CAPACITY];

    assert(reflow_caption(input, output, sizeof(output)));
    assert(strstr(output, "\r\n") != NULL);
}

static void test_tags_are_copied_atomically(void) {
    static const char input[] =
        "<SIZE 14>Alpha <FONT 1>Beta</FONT> Gamma";
    char output[COURT_RECORD_CAPTION_CAPACITY];

    assert(reflow_caption(input, output, sizeof(output)));
    assert(strstr(output, "<FONT 1>Beta</FONT>") != NULL);
}

int main(void) {
    test_known_caption();
    test_long_word_is_split();
    test_tags_are_copied_atomically();
    puts("Court Record hook tests passed.");
    return 0;
}
