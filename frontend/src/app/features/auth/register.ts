import { Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { HttpErrorResponse } from '@angular/common/http';
import { AuthService } from '../../core/auth.service';
import { Toast } from '../../core/toast.service';

@Component({
  selector: 'app-register', imports: [ReactiveFormsModule, RouterLink],
  template: `
  <main class="wrap">
    <form [formGroup]="form" (ngSubmit)="submit()" novalidate>
      <h1>Créer un compte</h1>
      <label class="field">Nom complet<input formControlName="full_name" autocomplete="name"></label>
      <label class="field">Organisation<input formControlName="organization_name" autocomplete="organization"></label>
      <label class="field">Adresse e-mail<input type="email" formControlName="email" autocomplete="username"></label>
      <label class="field">Mot de passe (10 caractères minimum)<input type="password" formControlName="password" autocomplete="new-password"
        [attr.aria-describedby]="'pwerr'"></label>
      <p id="pwerr" class="error" role="alert">{{ error() }}</p>
      <button class="btn" [disabled]="form.invalid || busy()">Créer le compte</button>
      <p class="muted">Déjà inscrit ? <a routerLink="/login">Se connecter</a></p>
    </form>
  </main>`,
  styles: [`.wrap { min-height: 100vh; display: grid; place-items: center; padding: 2rem; } form { background: var(--sheet); border: 1px solid var(--rule); padding: 2rem; width: min(26rem, 100%); } h1 { margin-bottom: 1.2rem; }`],
})
export class Register {
  private fb = inject(FormBuilder); private auth = inject(AuthService); private router = inject(Router); private toast = inject(Toast);
  form = this.fb.nonNullable.group({ full_name: ['', Validators.required], organization_name: ['', Validators.required],
    email: ['', [Validators.required, Validators.email]], password: ['', [Validators.required, Validators.minLength(10)]] });
  error = signal(''); busy = signal(false);
  async submit() {
    this.busy.set(true); this.error.set('');
    try {
      const mail = await this.auth.register(this.form.getRawValue());
      if (mail !== 'sent') this.toast.info('Compte créé. L’e-mail de vérification n’a pas pu être envoyé (SMTP non configuré).');
      this.router.navigateByUrl('/');
    } catch (e) { this.error.set(e instanceof HttpErrorResponse ? e.error?.error?.message ?? 'Inscription impossible.' : 'Inscription impossible.'); }
    finally { this.busy.set(false); }
  }
}
