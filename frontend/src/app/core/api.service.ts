import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { API } from './auth.service';

export interface TaskDto { id: string; title: string; agent: string; depends_on: string[]; status: string;
  tokens: number; duration_ms: number; error: string | null; output?: string | null; }
export interface ExecEvent { seq: number; kind: string; data: any; }
export interface ExecutionDto { id: string; status: string; mission: string; result: string | null; error: string | null; tokens: number; }
type R<T> = { success: true; data: T };

@Injectable({ providedIn: 'root' })
export class ApiService {
  private http = inject(HttpClient);
  get<T>(path: string, params?: Record<string, string | number | undefined>) {
    const clean = Object.fromEntries(Object.entries(params ?? {}).filter(([, v]) => v !== undefined && v !== '')) as Record<string, string | number>;
    return this.http.get<R<T>>(`${API}${path}`, { params: clean });
  }
  post<T>(path: string, body: unknown) { return this.http.post<R<T>>(`${API}${path}`, body); }
  put<T>(path: string, body: unknown) { return this.http.put<R<T>>(`${API}${path}`, body); }
  delete(path: string) { return this.http.delete<void>(`${API}${path}`); }
  upload<T>(path: string, form: FormData) { return this.http.post<R<T>>(`${API}${path}`, form); }
  blob(path: string) { return this.http.get(`${API}${path}`, { responseType: 'blob' }); }
}
