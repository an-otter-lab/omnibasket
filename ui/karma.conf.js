// Karma configuration for `ng test` (wired in angular.json -> test.options.karmaConfig).
// Same as the Angular default, with one change: every Chrome launcher starts with
// --disable-ipc-flooding-protection.
//
// Why (T1, flaky specs): Chrome allows about 200 navigations (pushState/replaceState and
// location.hash sets) per 10 s per page and then silently ignores further ones. Nearly every spec
// boots the app, which routes through the URL hash, so one run of the suite (~190 specs in ~2 s)
// makes 200+ navigations in a single window. Whichever specs ran after the limit saw their URL reset
// and their route changes dropped (e.g. "Expected '#/add' to be '#/find/Sapiens'"), so which specs
// failed depended on the random order. The flag turns that throttle off for the test browser only.
// The flags are added inside the launcher, so `--browsers=ChromeHeadless` gets them too.
const chromeLauncher = require('karma-chrome-launcher');

const NO_NAV_THROTTLE = '--disable-ipc-flooding-protection';

function withNoNavThrottle(Base) {
  function Launcher(baseBrowserDecorator, args) {
    const flags = (args && args.flags) || [];
    Base.call(this, baseBrowserDecorator, Object.assign({}, args, {
      flags: flags.includes(NO_NAV_THROTTLE) ? flags : flags.concat(NO_NAV_THROTTLE),
    }));
  }
  Launcher.prototype = Base.prototype;
  Launcher.$inject = Base.$inject;
  return Launcher;
}

const chromeLaunchers = {};
for (const [key, value] of Object.entries(chromeLauncher)) {
  if (key.startsWith('launcher:') && Array.isArray(value) && value[0] === 'type') {
    chromeLaunchers[key] = ['type', withNoNavThrottle(value[1])];
  }
}

module.exports = function (config) {
  config.set({
    basePath: '',
    frameworks: ['jasmine', '@angular-devkit/build-angular'],
    plugins: [
      require('karma-jasmine'),
      chromeLaunchers,
      require('karma-jasmine-html-reporter'),
      require('karma-coverage'),
      require('@angular-devkit/build-angular/plugins/karma'),
    ],
    client: {
      jasmine: {},
    },
    jasmineHtmlReporter: {
      suppressAll: true,
    },
    coverageReporter: {
      dir: require('path').join(__dirname, './coverage/ui'),
      subdir: '.',
      reporters: [{ type: 'html' }, { type: 'text-summary' }],
    },
    reporters: ['progress', 'kjhtml'],
    browsers: ['Chrome'],
    restartOnFileChange: true,
  });
};
