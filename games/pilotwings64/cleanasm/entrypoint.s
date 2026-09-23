/* Clean-room boot entry (n64cleanrecomp). Clears the kernel BSS, sets the
 * stack and jumps to bootproc. Same size as the original segment (0x50). */
.include "macro.inc"
.set noat
.set noreorder
.set gp=64
.section .text, "ax"

glabel entrypoint
    la      $t0, kernel_BSS_START
    li      $t1, 0x79A80            /* kernel BSS size (splat config) */
1:  sw      $zero, 0($t0)
    sw      $zero, 4($t0)
    addiu   $t1, $t1, -8
    bnez    $t1, 1b
     addiu  $t0, $t0, 8
    la      $sp, D_802C3C90
    la      $t2, bootproc
    jr      $t2
     nop
endlabel entrypoint
    .fill 0x50 - (. - entrypoint), 1, 0
