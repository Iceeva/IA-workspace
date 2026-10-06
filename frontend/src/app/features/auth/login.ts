import { Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { HttpErrorResponse } from '@angular/common/http';
import { AuthService } from '../../core/auth.service';

@Component({
  selector: 'app-login', imports: [ReactiveFormsModule, RouterLink],
  template: `
  <main class="login">
    <section class="intro">
      <h1>AI Workspace</h1>
      <p>Confiez une mission à une équipe d’agents. Suivez chaque tâche, chaque test et chaque correction, de la question initiale au résultat relu.</p>
    </section>
    <form [formGroup]="form" (ngSubmit)="submit()" novalidate>
      <h2>Connexion</h2>
      <label class="field">Adresse e-mail
        <input type="email" formControlName="email" autocomplete="username" [attr.aria-invalid]="form.controls.email.invalid && form.touched">
      </label>
      <label class="field">Mot de passe
        <input type="password" formControlName="password" autocomplete="current-password">
      </label>
      @if (error()) { <p class="error" role="alert">{{ error() }}</p> }
      <button class="btn" [disabled]="form.invalid || busy()">Se connecter</button>
      <p class="muted"><a routerLink="/forgot-password">Mot de passe oublié ?</a> · <a routerLink="/register">Créer un compte</a></p>
    </form>
  </main>`,
  styles: [`
    .login { min-height: 100%; display: grid; grid-template-columns: 1.2fr 1fr; align-items: center; gap: 4rem; padding: 4rem min(8vw, 7rem); }
    .intro p { max-width: 46ch; color: var(--ink-soft); font-size: 1.1rem; margin-top: 1rem; }
    .intro h1 { font-size: clamp(3rem, 7vw, 5.5rem); }
    form { background: var(--sheet); border: 1px solid var(--rule); padding: 2rem; max-width: 24rem; }
    form h2 { margin-bottom: 1.4rem; }
    @media (max-width: 800px) { .login { grid-template-columns: 1fr; gap: 2rem; padding: 2rem 1.2rem; } }
  `],
})
export class Login {
  private fb = inject(FormBuilder); private auth = inject(AuthService); private router = inject(Router);
  form = this.fb.nonNullable.group({ email: ['', [Validators.required, Validators.email]], password: ['', Validators.required] });
  error = signal(''); busy = signal(false);

  async submit() {
    this.busy.set(true); this.error.set('');
    try { await this.auth.login(this.form.controls.email.value, this.form.controls.password.value); this.router.navigateByUrl('/'); }
    catch (e) {
      const msg = e instanceof HttpErrorResponse ? e.error?.error?.message : null;
      this.error.set(msg ?? 'Connexion impossible. Vérifiez que l’API est démarrée.');
    } finally { this.busy.set(false); }
  }
}
