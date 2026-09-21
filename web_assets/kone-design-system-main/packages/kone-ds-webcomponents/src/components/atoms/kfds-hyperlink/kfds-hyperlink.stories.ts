export default {
    // this creates a ‘Components’ folder and a Hyperlink subfolder
    title: 'Components/Hyperlink',
    tags: ['autodocs'],
    argTypes: {
        linkClicked: { action: 'linkClicked', table: { type: { summary: 'EventEmitter' } } },
    },
    render: ({ ...args }) => {
        return `<kfds-hyperlink href="${args.href}">Link 1</kfds-hyperlink>`;
    },
    parameters: {
        docs: {
            source: { 
              code: `// React
import { KfdsRadio } from '@kone-ds/webcomponents-react';

<KfdsHyperlink href='javascript:void(0)' onLinkClicked={(event) => console.log('Link Clicked', event)}>Link</KfdsHyperlink>`,
            },
          },
    }
};


export const ExampleLink = {
    args: {
        href: 'https://www.kone.com/en/'
    }
};
