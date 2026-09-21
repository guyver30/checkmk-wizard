import { ButtonStyle, ButtonSize } from './kfds-button.enum';

export default {
    // this creates a ‘Components’ folder and a ‘Button’ subfolder
    title: 'Components/Button',
    tags: ['autodocs'],
    argTypes: {
        size: {
            control: { type: "select" }, 
            options: [ButtonSize.Extra, ButtonSize.Big, ButtonSize.Medium, ButtonSize.Small]
        },
        style: { 
            control: { type: "select"},
            options: [ButtonStyle.Primary, ButtonStyle.Secondary, ButtonStyle.Tertiary, ButtonStyle.Destructive, ButtonStyle.Borderless] 
        },
        buttonClicked: { action: 'buttonClicked', table: { type: { summary: 'EventEmitter' } } },
    },
    render: ({ ...args }) => {
        return `<kfds-button disabled="${args.disabled}" button-style="${args.style}" size="${args.size}">${args.label}</kfds-button>`;
    },
    parameters: {
        docs: {
            source: { 
              code: `// React
import { KfdsButton } from '@kone-ds/webcomponents-react';
import { ButtonStyle, ButtonSize } from '@kone-ds/webcomponents';

const handleButtonClick = (event: any) => {
    console.log('Button clicked', event);
};

<KfdsButton 
    size={ButtonSize.Medium} 
    button-style={ButtonStyle.Primary} 
    onButtonClicked={(event) => handleButtonClick(event)}
>
    Primary
</KfdsButton>`,
            },
          },
    }
};


export const PrimaryButton = {
    args: {
        label: 'Primary',
        style: ButtonStyle.Primary,
        disabled: false,
        size: ButtonSize.Big
    }
};

export const SecondaryButton = {
    args: {
        label: 'Secondary',
        style: ButtonStyle.Secondary,
        disabled: false,
        size: ButtonSize.Big
    }
};

export const TertiaryButton = { 
    args: {
        label: 'Tertiary',
        style: ButtonStyle.Tertiary,
        disabled: false,
        size: ButtonSize.Big
    }
};

export const DestructiveButton = {
    args: {
        label: 'Destructive',
        style: ButtonStyle.Destructive,
        disabled: false,
        size: ButtonSize.Big
    }
};

export const BorderlessButton = { 
    args: {
        label: 'Borderless',
        style: ButtonStyle.Borderless,
        disabled: false,
        size: ButtonSize.Big
    }
};
