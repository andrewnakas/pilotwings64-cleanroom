/* Clean-room bzero(ptr, len) (n64cleanrecomp); sized to the original slot (0xA0). */
.include "macro.inc"
.set noat
.set noreorder
.set gp=64
.section .text, "ax"

glabel bzero
    beqz    $a1, 2f
     nop
1:  sb      $zero, 0($a0)
    addiu   $a1, $a1, -1
    bnez    $a1, 1b
     addiu  $a0, $a0, 1
2:  jr      $ra
     nop
endlabel bzero
    .fill 0xA0 - (. - bzero), 1, 0
