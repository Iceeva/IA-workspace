import { TestBed } from '@angular/core/testing';
import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { authInterceptor } from './auth.interceptor';

describe('authInterceptor', () => {
  let http: HttpClient, ctl: HttpTestingController;
  beforeEach(() => {
    sessionStorage.clear(); sessionStorage.setItem('aiw.access', 'AAA'); sessionStorage.setItem('aiw.refresh', 'RRR'); sessionStorage.setItem('aiw.org', 'ORG1');
    TestBed.configureTestingModule({ providers: [provideRouter([]), provideHttpClient(withInterceptors([authInterceptor])), provideHttpClientTesting()] });
    http = TestBed.inject(HttpClient); ctl = TestBed.inject(HttpTestingController);
  });
  afterEach(() => ctl.verify());

  it('ajoute le jeton et l’organisation', () => {
    http.get('/api/projects').subscribe();
    const r = ctl.expectOne('/api/projects');
    expect(r.request.headers.get('Authorization')).toBe('Bearer AAA');
    expect(r.request.headers.get('X-Organization-Id')).toBe('ORG1');
    r.flush({});
  });
  it('rafraîchit sur 401 puis rejoue la requête', async () => {
    let body: unknown; http.get('/api/projects').subscribe(b => body = b);
    ctl.expectOne('/api/projects').flush({}, { status: 401, statusText: 'Unauthorized' });
    await Promise.resolve();
    const refresh = ctl.expectOne(r => r.url.endsWith('/api/auth/refresh'));
    refresh.flush({ success: true, data: { access_token: 'BBB', refresh_token: 'SSS' } });
    await new Promise(r => setTimeout(r));
    const retry = ctl.expectOne('/api/projects');
    expect(retry.request.headers.get('Authorization')).toBe('Bearer BBB');
    retry.flush({ ok: 1 });
    expect(body).toEqual({ ok: 1 });
  });
});
