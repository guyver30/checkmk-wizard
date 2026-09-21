import { RadioSize, RadioOrientation } from './kfds-radio.enum';

export default {
    // this creates a ‘Components’ folder and a Radio subfolder
    title: 'Components/Radio',
    tags: ['autodocs'],
    argTypes: {
        size: { 
            control: { type: "select" },
            options: [RadioSize.Small, RadioSize.Medium, RadioSize.Large] 
        },
        orientation: { 
            control: { type: "select" },
            options: [RadioOrientation.Vertical, RadioOrientation.Horizontal] 
        },
        radioClicked: { action: 'radioClicked', table: { type: { summary: 'EventEmitter' } } },
    },
    render: ({ ...args }) => {
        return `<kfds-radio label='${args.label}' orientation='${args.orientation}' size='${args.size}' disabled='${args.disabled}' options='${JSON.stringify(args.options)}' selected-option="${args.selectedOption}" name="exampleradio"></kfds-radio>`;
    },
    parameters: {
        docs: {
            source: { 
              code: `// React
import { KfdsRadio } from '@kone-ds/webcomponents-react';
import { RadioSize, RadioOrientation, RadioOption } from '@kone-ds/webcomponents';

const radioOptions: RadioOption[] = [{
    label: 'Option 1',
    value: 'option1',
    id: 'option1',      
    hintText: 'Hint Text 1'
  },
  {
    label: 'Option 2',
    value: 'option2',
    id: 'option2',      
    hintText: 'Hint Text 2'
  }];
const radioSelectedOption = 'option1';

<KfdsRadio 
    orientation={RadioOrientation.Vertical} 
    size={RadioSize.Medium} 
    options={radioOptions} 
    selectedOption={radioSelectedOption}
    onRadioClicked={(event) => console.log('Radio clicked', event)}
    label='Sample Radio' />`,
            },
          },
    }
};

const radioOptions = [{
    label: 'Option 1',
    value: 'option1',
    id: 'option1',      
    hintText: 'Hint Text 1'
  },
  {
    label: 'Option 2',
    value: 'option2',
    id: 'option2',      
    hintText: 'Hint Text 2'
}];

export const SmallRadio = { 
    args: {
        label: 'Small Radio',
        size: RadioSize.Small,
        options: radioOptions,
        selectedOption: 'option1',
        disabled: false,
        orientation: RadioOrientation.Vertical
    }
};

export const MediumRadio = { 
    args: {
        label: 'Medium Radio',
        size: RadioSize.Medium,
        options: radioOptions,
        selectedOption: 'option1',
        disabled: false,
        orientation: RadioOrientation.Vertical
    }
};

export const LargeRadio = {
    args: {
        label: 'Large Radio',
        size: RadioSize.Large,
        options: radioOptions,
        selectedOption: 'option1',
        disabled: false,
        orientation: RadioOrientation.Vertical
    }
};
