.section .text
.global _start
_start:
.type nested,@function
.global nested
nested:
.Louter:
  addi x10,x10,1
.Linner:
  addi x11,x11,1
  blt x11,x12,.Linner
  blt x10,x13,.Louter
  ret
.size nested,.-nested

.type multi,@function
.global multi
multi:
.Lheader:
  beq x10,x0,.Lright
  addi x11,x11,1
  blt x11,x12,.Lheader
  ret
.Lright:
  addi x12,x12,1
  blt x12,x13,.Lheader
  ret
.size multi,.-multi

.type irreducible,@function
.global irreducible
irreducible:
  beq x10,x0,.Lb
.La:
  addi x11,x11,1
  j .Lb
.Lb:
  blt x11,x12,.La
  ret
.size irreducible,.-irreducible

.type indirect,@function
.global indirect
indirect:
  addi x11,x11,1
  blt x11,x12,indirect
  jr x10
.size indirect,.-indirect

.type pointer_loop,@function
.global pointer_loop
pointer_loop:
  lw x12,0(x11)
  mv x14,x10
  add x27,x10,x12
.Lpointer:
  lb x13,0(x14)
  addi x14,x14,1
  bne x27,x14,.Lpointer
  ret
.size pointer_loop,.-pointer_loop

.type changing_boundary,@function
.global changing_boundary
changing_boundary:
.Lchanging:
  lb x13,0(x14)
  addi x14,x14,1
  addi x27,x27,1
  bne x27,x14,.Lchanging
  ret
.size changing_boundary,.-changing_boundary

.type reverse_pointer,@function
.global reverse_pointer
reverse_pointer:
.Lreverse:
  lb x13,0(x14)
  addi x14,x14,-1
  bne x27,x14,.Lreverse
  ret
.size reverse_pointer,.-reverse_pointer
