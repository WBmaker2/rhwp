# Task 2506 Stage 1 - Chrome manifest version single source

## Scope

- Integrate [#2506](https://github.com/edwardkim/rhwp/pull/2506): read the extension version from the Chrome manifest in the content script, then pass that DOM attribute to the page-context DevTools helper.
- Preserve the Firefox-equivalent ordering: set the version attribute before injecting `dev-tools-inject.js`.

## Validation plan

1. Confirm the Chrome sources no longer contain a duplicated extension version literal.
2. Confirm the content script sets the DOM attribute before injecting the page-context helper.
3. Run JavaScript syntax checks and a local Chrome production build without publishing or installing an extension.

## Correction

- The contributor helper initially read `data-rhwp-extension-version`, while the Chrome content script, Firefox implementation, and extension build guide use `data-hwp-extension-version`.
- Keep the established `data-hwp-extension-version` contract and add a source-level regression test for the producer/consumer pair and injection ordering.

## Result

- Chrome now reads its version from `chrome.runtime.getManifest().version` and passes the same established DOM attribute to the page-context DevTools helper.
- The regression test verifies the dynamic source, producer/consumer attribute agreement, and ordering before helper injection.
- The focused Chrome test suite passed 15 tests, and the local production extension build completed without publishing or installing it.
