/* Clean-room sqrtf(x) (n64cleanrecomp); sized to the original slot (0x10). */
.include "macro.inc"
.set noat
.set noreorder
.set gp=64
.section .text, "ax"

glabel sqrtf
    jr      $ra
     sqrt.s $f0, $f12
endlabel sqrtf
    .fill 0x10 - (. - sqrtf), 1, 0
