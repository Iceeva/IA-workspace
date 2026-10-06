import { Injectable, inject } from '@angular/core';
import { MatSnackBar } from '@angular/material/snack-bar';

@Injectable({ providedIn: 'root' })
export class Toast {
  private bar = inject(MatSnackBar);
  info(msg: string) { this.bar.open(msg, 'OK', { duration: 3500 }); }
  error(msg: string) { this.bar.open(msg, 'Fermer', { duration: 7000, panelClass: 'toast-error' }); }
}
