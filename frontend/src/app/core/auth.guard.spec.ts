import { TestBed } from '@angular/core/testing';
import { Router, UrlTree, provideRouter } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { authGuard } from './auth.guard';
import { AuthService } from './auth.service';

describe('authGuard', () => {
  beforeEach(() => { sessionStorage.clear(); TestBed.configureTestingModule({ providers: [provideRouter([]), provideHttpClient()] }); });

  it('redirige vers /login sans session', () => {
    const r = TestBed.runInInjectionContext(() => authGuard({} as any, {} as any));
    expect(r instanceof UrlTree).toBeTrue();
    expect(TestBed.inject(Router).serializeUrl(r as UrlTree)).toBe('/login');
  });
  it('laisse passer avec un jeton', () => {
    sessionStorage.setItem('aiw.access', 'x');
    TestBed.resetTestingModule(); TestBed.configureTestingModule({ providers: [provideRouter([]), provideHttpClient()] });
    expect(TestBed.runInInjectionContext(() => authGuard({} as any, {} as any))).toBeTrue();
    expect(TestBed.inject(AuthService).isAuthenticated()).toBeTrue();
  });
});
