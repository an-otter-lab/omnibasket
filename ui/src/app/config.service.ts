import { Injectable } from '@angular/core';
import { Observable, of } from 'rxjs';

export interface AppConfig {
  demo: boolean;
}

/**
 * Reads the app configuration from the API. If the /config endpoint is not
 * available (branch 4 hasn't landed yet), returns a default config with
 * demo: false.
 *
 * When the /config endpoint lands, it should return { demo: boolean } based
 * on the --demo flag or OMNIBASKET_DEMO=1 environment variable.
 */
@Injectable({ providedIn: 'root' })
export class ConfigService {
  private cachedConfig: AppConfig | null = null;

  getConfig(): Observable<AppConfig> {
    if (this.cachedConfig) {
      return of(this.cachedConfig);
    }

    return new Observable<AppConfig>((observer) => {
      fetch('/config')
        .then((res) => {
          if (!res.ok) {
            throw new Error('config endpoint not available');
          }
          return res.json();
        })
        .then((json) => {
          const config: AppConfig = {
            demo: !!json.demo,
          };
          this.cachedConfig = config;
          observer.next(config);
          observer.complete();
        })
        .catch(() => {
          // Config endpoint not available yet, return default
          const config: AppConfig = { demo: false };
          this.cachedConfig = config;
          observer.next(config);
          observer.complete();
        });
    });
  }
}
