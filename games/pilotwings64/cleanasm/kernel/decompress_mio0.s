/* Clean-room MIO0 decompressor and two CP0 helpers (n64cleanrecomp).
 * Written from the MIO0 format description; laid out to the original
 * segment's size (0xB0) so everything after it keeps its address. */
.include "macro.inc"
.set noat
.set noreorder
.set gp=64
.section .text, "ax"

/* u32 func_80231A10(u32 count): swap the CP0 Count register. */
glabel func_80231A10
    mfc0    $v0, $9
    jr      $ra
     mtc0   $a0, $9
endlabel func_80231A10

glabel func_80231A1C
    jr      $ra
endlabel func_80231A1C

/* void mio0_decompress(void *src, u8 *dst) */
glabel mio0_decompress
    lw      $t0, 4($a0)             /* decompressed size */
    lw      $t1, 8($a0)             /* back-reference stream offset */
    lw      $t2, 12($a0)            /* literal stream offset */
    addu    $t0, $t0, $a1           /* end of output */
    addu    $t1, $t1, $a0
    addu    $t2, $t2, $a0
    addiu   $t3, $a0, 16            /* flag words */
    b       .Lnext
     move   $t4, $zero              /* flag bits left */
.Lref:
    lhu     $t7, 0($t1)
    addiu   $t1, $t1, 2
    srl     $t8, $t7, 12
    addiu   $t8, $t8, 3             /* length */
    andi    $t7, $t7, 0xFFF
    subu    $t7, $a1, $t7
    addiu   $t7, $t7, -1            /* source = out - (distance + 1) */
.Lcopy:
    lbu     $t9, 0($t7)
    addiu   $t7, $t7, 1
    addiu   $t8, $t8, -1
    sb      $t9, 0($a1)
    bnez    $t8, .Lcopy
     addiu  $a1, $a1, 1
.Lnext:
    beq     $a1, $t0, .Ldone
     nop
    bnez    $t4, .Lhave
     addiu  $t4, $t4, -1
    lw      $t5, 0($t3)
    addiu   $t3, $t3, 4
    li      $t4, 31
.Lhave:
    srlv    $t6, $t5, $t4
    andi    $t6, $t6, 1
    beqz    $t6, .Lref
     lbu    $t7, 0($t2)             /* literal (ignored on the reference path) */
    addiu   $t2, $t2, 1
    sb      $t7, 0($a1)
    b       .Lnext
     addiu  $a1, $a1, 1
.Ldone:
    jr      $ra
     nop
endlabel mio0_decompress
    .fill 0xB0 - (. - func_80231A10), 1, 0
