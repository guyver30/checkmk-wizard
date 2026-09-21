import {defineCustomElements} from '../loader';
import "@kone-ds/fonts/dist/fonts.css";

defineCustomElements();

export const parameters = {
  actions: { argTypesRegex: "^on[A-Z].*" },
  controls: {
    matchers: {
      color: /(background|color)$/i,
      date: /Date$/,
    },
  },
}

// export const argTypes = { theme: { control: 'select', options: ['light', 'dark'] } };

// export const args = { theme: 'light' };
