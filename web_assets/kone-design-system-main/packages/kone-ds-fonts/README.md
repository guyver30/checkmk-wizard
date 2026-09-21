# `kone-ds-fonts`

In a `/dist` folder you can find compiled css files containing font definitions and font binaries. While fonts.css need all font files attached externally, the font-encoded.css is a standalone file containing everything.

If you're interested in independent bundling, use partial scss files from `/src`

The package contains:

- KONE Information: the base font for headers, eg. `h1 {font-fmaily: 'KONE-Information', sans-serif;}`
- KONE Icon Font: besides the icon font itself, the package contains a set of semantical classes so you don't have to remember hex codes, eg. `<i class="kfds-icon-accept-checkmark"></i>`. Open the `dist/demo.html` after build to check all the icon-fonts this package contains.
