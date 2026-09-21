import { SelectShape, SelectSize } from './kfds-select.enum';

export default {
  // this creates a ‘Components’ folder and a Select subfolder
  title: 'Components/Select',
  tags: ['autodocs'],
  argTypes: {
    size: {
      control: { type: 'select' },
      options: [SelectSize.Small, SelectSize.Medium, SelectSize.Large, SelectSize.Inline],
    },
    shape: {
      control: { type: 'select' },
      options: [SelectShape.Rounded, SelectShape.Pill],
    },
    selectChange: { action: 'selectChange', table: { type: { summary: 'EventEmitter' } } },
    selectBlur: { action: 'selectBlur', table: { type: { summary: 'EventEmitter' } } },
  },
  render: ({ ...args }) => {
    return `<kfds-select options='${JSON.stringify(args.options)}' shape='${args.shape}' size='${args.size}' disabled='${args.disabled}' label='${args.label}' supporting-text='${args.supportingText}' placeholder='${args.placeholder}' custom-class='${args.customClass}' required='${args.required}' name='sampleselect'></kfds-select>`;
  },
  parameters: {
    docs: {
        source: { 
          code: `// React
import { KfdsSelect } from '@kone-ds/webcomponents-react';
import { SelectShape, SelectSize, selectOption } from '@kone-ds/webcomponents';

const selectOptions: selectOption[] = [{
  label: 'Option 1',
  value: 'option1'
},
{
  label: 'Option 2',
  value: 'option2'
}];
const selectOption = 'option1';

<KfdsSelect 
  size={SelectSize.Medium} 
  shape={SelectShape.Rounded}
  options={selectOptions} 
  selectedOption={selectOption}
  onSelectChange={(event) => console.log('drop down changed', event)}
  onSelectBlur={(event) => console.log('drop down blue event', event)}
  label='Sample drop down' />`,
        },
      },
  }
};

const selectOptions = [{
  label: 'Option 1',
  value: 'option1'
},
{
  label: 'Option 2',
  value: 'option2'
}];

export const SmallSelect = {
  args: {
    options: selectOptions,
    label: 'Label',
    size: SelectSize.Small,
    shape: SelectShape.Rounded,
    disabled: false,
    supportingText: 'Supporting Text',
    placeholder: 'Select',
    customClass: '',
    required: true,
  },
};

export const MediumSelect = {
  args: {
    options: selectOptions,
    size: SelectSize.Medium,
    label: 'Label',
    shape: SelectShape.Rounded,
    disabled: false,
    supportingText: 'Supporting Text',
    placeholder: 'Select',
    customClass: 'error',
    required: true,
  },
};

export const LargeSelect = {
  args: {
    options: selectOptions,
    size: SelectSize.Large,
    label: 'Label',
    shape: SelectShape.Rounded,
    disabled: false,
    supportingText: 'Supporting Text',
    placeholder: 'Select',
    customClass: '',
    required: true,
  },
};

export const InlineSelect = {
  args: {
    options: selectOptions,
    size: SelectSize.Inline,
    label: 'Label',
    shape: SelectShape.Rounded,
    disabled: false,
    placeholder: 'Select',
    customClass: '',
    required: true,
  },
};
