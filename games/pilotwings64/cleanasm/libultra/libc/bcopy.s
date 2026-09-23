/* Clean-room bcopy(src, dst, len) with memmove semantics (n64cleanrecomp).
 * Byte loop; sized to the original slot (0x310) so later code keeps its address. */
.include "macro.inc"
.set noat
.set noreorder
.set gp=64
.section .text, "ax"

glabel bcopy
    beqz    $a2, .Lret
     sltu   $t0, $a1, $a0           /* dst < src: copy forwards */
    bnez    $t0, .Lfwd
     addu   $t1, $a0, $a2
    sltu    $t0, $a1, $t1           /* dst inside [src, src+len): backwards */
    bnez    $t0, .Lback
     nop
.Lfwd:
    lbu     $t2, 0($a0)
    addiu   $a0, $a0, 1
    addiu   $a2, $a2, -1
    sb      $t2, 0($a1)
    bnez    $a2, .Lfwd
     addiu  $a1, $a1, 1
    b       .Lret
     nop
.Lback:
    addu    $a0, $a0, $a2
    addu    $a1, $a1, $a2
1:  addiu   $a0, $a0, -1
    addiu   $a1, $a1, -1
    lbu     $t2, 0($a0)
    addiu   $a2, $a2, -1
    bnez    $a2, 1b
     sb     $t2, 0($a1)
.Lret:
    jr      $ra
     nop
endlabel bcopy
    .fill 0x310 - (. - bcopy), 1, 0
