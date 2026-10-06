import { Component, inject, input, signal, OnInit } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { API } from '../../core/auth.service';
import { errorMessage } from '../../core/errors';

const STYLE = `.wrap { min-height: 100vh; display: grid; place-items: center; padding: 2rem; } .card { background: var(--sheet); border: 1px solid var(--rule); padding: 2rem; width: min(26rem, 100%); } h1 { margin-bottom: 1rem; }`;

@Component({
  selector: 'app-forgot', imports: [ReactiveFormsModule, RouterLink], styles: [STYLE],
  template: `<main class="wrap"><form class="card" [formGroup]="form" (ngSubmit)="submit()">
    <h1>Mot de passe oublié</h1>
    @if (sent()) { <p role="status">Si ce compte existe, un e-mail de réinitialisation vient d’être envoyé.</p> }
    @else { <label class="field">Adresse e-mail<input type="email" formControlName="email" autocomplete="username"></label>
      @if (error()) { <p class="error" role="alert">{{ error() }}</p> }
      <button class="btn" [disabled]="form.invalid">Envoyer le lien</button> }
    <p><a routerLink="/login">Retour à la connexion</a></p></form></main>`,
})
export class ForgotPassword {
  private http = inject(HttpClient); private fb = inject(FormBuilder);
  form = this.fb.nonNullable.group({ email: ['', [Validators.required, Validators.email]] });
  sent = signal(false); error = signal('');
  async submit() {
    try { await firstValueFrom(this.http.post(`${API}/api/auth/forgot-password`, this.form.getRawValue())); this.sent.set(true); }
    catch (e) { this.error.set(errorMessage(e)); }
  }
}

@Component({
  selector: 'app-reset', imports: [ReactiveFormsModule, RouterLink], styles: [STYLE],
  template: `<main class="wrap"><form class="card" [formGroup]="form" (ngSubmit)="submit()">
    <h1>Nouveau mot de passe</h1>
    @if (done()) { <p role="status">Mot de passe mis à jour.</p><a class="btn" routerLink="/login">Se connecter</a> }
    @else { <label class="field">Mot de passe (10 caractères minimum)<input type="password" formControlName="password" autocomplete="new-password"></label>
      @if (error()) { <p class="error" role="alert">{{ error() }}</p> }
      <button class="btn" [disabled]="form.invalid">Enregistrer</button> }
  </form></main>`,
})
export class ResetPassword {
  token = input<string>('');
  private http = inject(HttpClient); private fb = inject(FormBuilder);
  form = this.fb.nonNullable.group({ password: ['', [Validators.required, Validators.minLength(10)]] });
  done = signal(false); error = signal('');
  async submit() {
    try { await firstValueFrom(this.http.post(`${API}/api/auth/reset-password`, { token: this.token(), ...this.form.getRawValue() })); this.done.set(true); }
    catch (e) { this.error.set(errorMessage(e)); }
  }
}

@Component({
  selector: 'app-verify', imports: [RouterLink], styles: [STYLE],
  template: `<main class="wrap"><div class="card"><h1>Vérification de l’e-mail</h1>
    <p role="status">{{ msg() }}</p><a routerLink="/login">Continuer</a></div></main>`,
})
export class VerifyEmail implements OnInit {
  token = input<string>('');
  private http = inject(HttpClient);
  msg = signal('Vérification en cours…');
  async ngOnInit() {
    try { await firstValueFrom(this.http.post(`${API}/api/auth/verify-email`, { token: this.token() })); this.msg.set('Adresse confirmée, merci.'); }
    catch (e) { this.msg.set(errorMessage(e)); }
  }
}
