import { BannerType, BannerPosition } from './kfds-banner.enum';

export default {
    // this creates a ‘Components’ folder and a Banner subfolder
    title: 'Components/Banner',
    tags: ['autodocs'],
    argTypes: {
        type: { 
            control: { type: "select" },
            options: [BannerType.Info, BannerType.Success, BannerType.Warning, BannerType.Error] 
        },
    },
    render: ({ ...args }) => {
        return `<kfds-banner actions='${JSON.stringify(args.actions)}' duration=${args.duration} type='${args.type}' message='${args.message}' position='${args.position}'></kfds-banner>`;
    },
    parameters: {
        docs: {
            source: { 
              code: `// React
import { KfdsBanner } from '@kone-ds/webcomponents-react';
import { BannerPosition, BannerType } from '@kone-ds/webcomponents';

const bannerActions = [{
label: 'Link 1',
href: 'javascript:void(0)'
},
{
label: 'Link 2',
href: 'javascript:void(0)'
}];

<KfdsBanner
    type={BannerType.Success}
    position={BannerPosition.Top}
    message='Banner Message'
    actions={bannerActions}
    onActionLinkClicked={(event) => console.log('action clicked', event)}
/>`,
            },
          },
    }
};

const bannerActions = [{
    label: 'Link 1',
    href: 'option1'
  },
  {
    label: 'Link 2',
    href: 'option2'
}];


export const InfoBanner = { 
    args: {
        type: BannerType.Info,
        actions: bannerActions.slice(0, 1),
        message: 'Long title text',
        position: BannerPosition.Top
    }
};

export const SuccessBanner = { 
    args: {
        type: BannerType.Success,
        actions: bannerActions,
        message: 'Long title text',
        position: BannerPosition.Top
    }
};

export const WarningBanner = { 
    args: {
        type: BannerType.Warning,
        actions: bannerActions,
        message: 'Long title text',
        position: BannerPosition.Bottom
    }
};

export const ErrorBanner = { 
    args: {
        type: BannerType.Error,
        message: 'Long title text',
        actions: bannerActions,
        position: BannerPosition.Bottom
    }
};
