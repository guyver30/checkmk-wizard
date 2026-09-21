# Kone Design System

Collection of documents, articles, examples, code snippets, screenshots, design guidelines, components, philosophies and other digital assets.

## Packages

* **kone-ds-assets** - binary assets including icons, images, logos, etc
* **kone-ds-fonts** - necessary webfonts and (s)css definitions
* **kone-ds-tokens** - convert Figma design tokens to web usable formats css, scss
* **kone-ds-webcomponents** - stencil.js component library
* **kone-ds-webcomponents-angular** - angular wrapper of stencil.js component library
* **kone-ds-webcomponents-react** - react wrapper of stencil.js component library

## Setup

1. Make sure you have Node.js version 18+ installed with accompanying npm.
2. Make sure you have yarn installed globally.
3. Run `npm install -f` in the main project's directory
4. Run `npm run build`
5. Run `npm start` to start the storybook in local

While working on the project all packages are linked together. You can run npm scripts for all packages at once with Lerna, eg:
```
npx lerna run build
```
or selectively:
```
npx lerna run start --scope=kone-ds-fonts
```
It's also possible (though not suggested) to navigate to some package and run scripts there, eg:
```
cd packages/kone-ds-fonts
npm run start
```

### Release 

Run "npm run release" and commit it whenever you want to release the package to artifact.