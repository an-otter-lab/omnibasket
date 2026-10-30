import { TestBed } from '@angular/core/testing';
import { ConfigService } from './config.service';

/**
 * Test helper: demo mode on, and the sample asked for, the way the demo link does it.
 * Call it BEFORE TestBed.createComponent(AppComponent): the constructor reads the config and the URL.
 * The URL is cleaned between specs by test-isolation.spec.ts (only when dirty: the History API is throttled).
 */
export function demoSample(): void {
  (TestBed.inject(ConfigService) as unknown as { cachedConfig: { demo: boolean } }).cachedConfig = { demo: true };
  // Land on the result route the way the demo link does, so the constructor does not set the hash itself.
  window.history.replaceState(null, '', window.location.pathname + '?sample=ro-v1' + (window.location.hash || '#/result/cheapest'));
}
