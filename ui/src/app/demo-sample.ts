import { TestBed } from '@angular/core/testing';
import { ConfigService } from './config.service';

/** Test helper: demo mode on, and the sample asked for, the way the demo link does it. */
export function demoSample(): void {
  (TestBed.inject(ConfigService) as unknown as { cachedConfig: { demo: boolean } }).cachedConfig = { demo: true };
  window.history.replaceState(null, '', window.location.pathname + '?sample=ro-v1' + window.location.hash);
}

afterEach(() => window.history.replaceState(null, '', window.location.pathname + window.location.hash));
