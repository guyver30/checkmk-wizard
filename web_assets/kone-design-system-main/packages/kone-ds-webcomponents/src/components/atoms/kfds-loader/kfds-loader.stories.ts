export default {
  // this creates a ‘Components’ folder and a 'Loader' subfolder
  title: 'Components/Loader',
  tags: ['autodocs'],
  description: 'Web Component for the loader, the loading progress state of the loader controlled by `now` prop of the Component',
  argTypes: {
    now: {
      control: {
        type: 'number',
        required: true,
      },
      defaultValue: 0,
      description: 'Input to the Loader Progress state value, Must between from 1 to 100',
    },
    progressBar: {
      control: { type: 'select' },
      options: ['show', 'hidden'],
    },
    progressNum: {
      control: { type: 'select' },
      options: ['show', 'hidden'],
    },
    restartButton: {
      control: { type: 'select' },
      options: ['show', 'hidden'],
      description: 'Restart Button to simulate the now input value from 1 to 100, Use it only for debugging',
    },
    videoBackground: {
      control: { type: 'select' },
      options: ['show', 'hidden'],
    },
  },
  render: ({ ...args }) => {
    return `<kfds-loader 
    app-name='${args.appName}' 
    now=${args.now} 
    progress-bar=${args.progressBar} 
    progress-num=${args.progressNum}  
    restart-button=${args.restartButton} 
    video-background=${args.videoBackground}>
    </kfds-loader>`;
  },
  parameters: {
    docs: {
        source: { 
          code: `// React
import { KfdsLoader } from '@kone-ds/webcomponents-react';

<KfdsLoader 
  element-id='loader' 
  app-name='KONE Flow Design System'
  progress-bar='show'
  progress-num='show'
  now={50}
/>
`,
        },
      },
  }
};
export const LoaderWithAllInput = {
  args: {
    appName: 'Field Service Mobility',
    now: 46,
    progressBar: 'show',
    videoBackground: 'show',
    restartButton: 'show',
  },
};

export const LoaderWithBackground = {
  args: {
    appName: 'Field Service Mobility',
    now: 30,
    videoBackground: 'show',
  },
};
export const LoaderWithProgressBar = {
  args: {
    appName: 'Field Service Mobility',
    progressBar: 'show',
    now: 60,
  },
};
