import { Component, inject } from '@angular/core';
import { I18nService } from './i18n';
import { Lang } from './messages';
import { ThemePref, ThemeService } from './theme';

/** Feature 8: the RO/EN toggle and the System/Light/Dark theme setting, above every screen. */
@Component({
  selector: 'app-settings',
  template: `
    <div class="prefs" role="group" [attr.aria-label]="m.prefsLabel">
      <div class="seg" role="group" [attr.aria-label]="m.langLabel">
        @for (l of langs; track l) {
          <button type="button" class="segb" [attr.lang]="l" [attr.aria-pressed]="lang === l" [attr.aria-label]="l === 'en' ? m.langEnName : m.langRoName" (click)="setLang(l)">{{ l === 'en' ? m.langEn : m.langRo }}</button>
        }
      </div>
      <div class="seg" role="group" [attr.aria-label]="m.themeLabel">
        @for (t of themes; track t) {
          <button type="button" class="segb" [attr.data-theme-option]="t" [attr.aria-pressed]="pref === t" (click)="setTheme(t)">{{ themeName(t) }}</button>
        }
      </div>
    </div>
  `,
})
export class SettingsComponent {
  private readonly i18n = inject(I18nService);
  private readonly themeService = inject(ThemeService);
  readonly langs: Lang[] = ['en', 'ro'];
  readonly themes: ThemePref[] = ['system', 'light', 'dark'];
  get m() {
    return this.i18n.m();
  }
  get lang(): Lang {
    return this.i18n.lang();
  }
  get pref(): ThemePref {
    return this.themeService.pref();
  }
  setLang(l: Lang): void {
    this.i18n.choose(l);
  }
  setTheme(t: ThemePref): void {
    this.themeService.choose(t);
  }
  themeName(t: ThemePref): string {
    return t === 'system' ? this.m.themeSystem : t === 'light' ? this.m.themeLight : this.m.themeDark;
  }
}
