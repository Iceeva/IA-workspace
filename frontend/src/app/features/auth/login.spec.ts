import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { Login } from './login';

describe('Login', () => {
  beforeEach(() => TestBed.configureTestingModule({ imports: [Login], providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()] }));

  it('désactive l’envoi tant que le formulaire est invalide', () => {
    const f = TestBed.createComponent(Login); f.detectChanges();
    const btn: HTMLButtonElement = f.nativeElement.querySelector('button.btn');
    expect(btn.disabled).toBeTrue();
    f.componentInstance.form.setValue({ email: 'a@b.io', password: 'secret' }); f.detectChanges();
    expect(btn.disabled).toBeFalse();
  });
  it('refuse un e-mail mal formé', () => {
    const f = TestBed.createComponent(Login);
    f.componentInstance.form.setValue({ email: 'pas-un-mail', password: 'x' });
    expect(f.componentInstance.form.controls.email.invalid).toBeTrue();
  });
});
