import { Config } from '@stencil/core';
import { sass } from '@stencil/sass';
import { reactOutputTarget } from '@stencil/react-output-target';
import { angularOutputTarget, ValueAccessorConfig  } from '@stencil/angular-output-target';

export const config: Config = {
  namespace: 'kone-ds-webcomponents',
  plugins: [
    sass({
      injectGlobalPaths: [
        'src/globals/global.scss',
      ]
    }),
  ],
  outputTargets: [
    angularOutputTarget({
      componentCorePackage: '@kone-ds/webcomponents',
      directivesProxyFile: '../kone-ds-webcomponents-angular/projects/kone-ds-webcomponents-angular/src/lib/stencil-generated/components.ts',
      directivesArrayFile: '../kone-ds-webcomponents-angular/projects/kone-ds-webcomponents-angular/src/lib/stencil-generated/index.ts',
    }),
    reactOutputTarget({
      componentCorePackage: '@kone-ds/webcomponents',
      proxiesFile: '../kone-ds-webcomponents-react/src/components/stencil-generated/index.ts',
      includeDefineCustomElements: true
    }),
    {
      type: 'dist',
      esmLoaderPath: '../loader',
      copy: [
        { src: '../../kone-ds-assets/dist/icons/*.svg', dest: 'icons', warn: true },
        { src: '../../kone-ds-fonts/dist/fonts/{*.woff2,*.woff,*.ttf,*.eot,*.svg}', dest: 'fonts', warn: true },
      ]
    },
    {
      type: 'dist-custom-elements',
      copy: [
        { src: '../../kone-ds-assets/dist/icons/*.svg', dest: 'dist/components/icons', warn: true },
        { src: '../../kone-ds-fonts/dist/fonts/{*.woff2,*.woff,*.ttf,*.eot,*.svg}', dest: 'dist/components/fonts', warn: true },
      ]
    },
    {
      type: 'docs-readme',
    },
    {
      type: 'www',
      serviceWorker: null, // disable service workers
      // copy: [{ src: '../../kone-ds-fonts/dist/fonts/{*.woff2,*.woff}', dest: 'build' }],
    },
  ],
  extras: {
    enableImportInjection: true,
  }
};
