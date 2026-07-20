# Task 2506 Stage 1 - Chrome manifest version single source

## Scope

- Integrate [#2506](https://github.com/edwardkim/rhwp/pull/2506): read the extension version from the Chrome manifest in the content script, then pass that DOM attribute to the page-context DevTools helper.
- Preserve the Firefox-equivalent ordering: set the version attribute before injecting `dev-tools-inject.js`.

## Validation plan

1. Confirm the Chrome sources no longer contain a duplicated extension version literal.
2. Confirm the content script sets the DOM attribute before injecting the page-context helper.
3. Run JavaScript syntax checks and a local Chrome production build without publishing or installing an extension.
