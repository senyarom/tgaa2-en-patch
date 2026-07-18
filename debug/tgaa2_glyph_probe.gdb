set pagination off
set confirm off
set architecture armv6
target remote 127.0.0.1:24689

set logging file build/glyph-widths.csv
set logging overwrite on
set logging redirect on
set logging enabled on

set $capture = 0
set $glyph_index = 0
set $caption_node = 0

# The Court Record hook receives the detail object in r0.  Its caption widget
# is the fourth pointer in that object.  Saving it lets the glyph breakpoint
# ignore the item name and every unrelated UI text layout.
hbreak *0x005bda90
commands
  silent
  set $caption_node = *(unsigned int *)($r0 + 0x0c)
  set $glyph_index = 0
  set $capture = 1
  continue
end

# This is the end of the ordinary glyph branch in the game's layout loop.
hbreak *0x002e5504
condition 2 $capture != 0 && *(unsigned int *)($r5 + 0x10) == $caption_node
commands
  silent
  set $glyph = $r8
  printf "%u,0x%08x,0x%08x,0x%08x,%d,%d,%f,%f,%f,%f,%f,%f,%f,%f\n", $glyph_index, $glyph, *(unsigned int *)($glyph + 0x08), *(unsigned int *)($glyph + 0x0c), *(signed char *)($glyph + 0x10), *(signed char *)($glyph + 0x11), *(float *)($r4 + 0x04), *(float *)($r4 + 0x08), *(float *)($r4 + 0x10), *(float *)($r4 + 0x14), *(float *)($r4 + 0x18), *(float *)($r4 + 0x1c), *(float *)($r4 + 0x20), *(float *)($r4 + 0x24)
  set $glyph_index = $glyph_index + 1
  if $glyph_index >= 93
    set $capture = 0
    set logging enabled off
    detach
    quit
  end
  continue
end

printf "index,glyph,raw8,rawc,bearing_x,bearing_y,f04,f08,f10,f14,f18,f1c,f20,f24\n"
continue
