import { CheckboxSize, CheckboxOrientation } from './kfds-checkbox.enum';

export default {
    // this creates a ‘Components’ folder and a Checkbox subfolder
    title: 'Components/Checkbox',
    tags: ['autodocs'],
    argTypes: {
        size: { 
            control: { type: "select" },
            options: [CheckboxSize.Small, CheckboxSize.Medium, CheckboxSize.Large] 
        },
        orientation: { 
            control: { type: "select" },
            options: [CheckboxOrientation.Vertical, CheckboxOrientation.Horizontal] 
        },
        checkboxClicked: { action: 'checkboxClicked', table: { type: { summary: 'EventEmitter' } } },
    },
    render: ({ ...args }) => {
        return `<kfds-checkbox label='${args.label}' orientation='${args.orientation}' size='${args.size}' disabled='${args.disabled}' options='${JSON.stringify(args.options)}' selected-options='${JSON.stringify(args.selectedOptions)}' name="examplecheckbox"></kfds-checkbox>`;
    },
    parameters: {
        docs: {
            source: { 
              code: `// React
import { KfdsCheckbox } from '@kone-ds/webcomponents-react';
import { CheckboxOrientation, CheckboxSize, CheckboxOption } from '@kone-ds/webcomponents';

const checkboxOptions: CheckboxOption[] = [{
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
const selectedOptions: any = ['option1'];

<KfdsCheckbox 
    orientation={CheckboxOrientation.Vertical} 
    size={CheckboxSize.Medium} 
    options={checkboxOptions} 
    selectedOptions={selectedOptions}
    onCheckboxClicked={(event) => console.log('Checkbox clicked', event)}
    label='Checkbox' />`,
            },
          },
    }
};

const checkboxOptions = [{
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

export const SmallCheckBox = {
    args: {
        label: 'Small Checkbox',
        size: CheckboxSize.Small,
        options: checkboxOptions,
        selectedOptions: ['option1'],
        disabled: false,
        orientation: CheckboxOrientation.Vertical
    }
};

export const MediumCheckBox = {
    args: {
        label: 'Medium Checkbox',
        size: CheckboxSize.Medium,
        options: checkboxOptions,
        selectedOptions: ['option1'],
        disabled: false,
        orientation: CheckboxOrientation.Vertical
    }
};

export const LargeCheckBox = {
    args: {
        label: 'Large Checkbox',
        size: CheckboxSize.Large,
        options: checkboxOptions,
        selectedOptions: ['option1'],
        disabled: false,
        orientation: CheckboxOrientation.Vertical
    }
};
