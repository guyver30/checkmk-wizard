import { InputShape, InputSize } from './kfds-input.enum';

export default {
  // this creates a ‘Components’ folder and a Input subfolder
  title: 'Components/Input',
  tags: ['autodocs'],
  argTypes: {
    size: {
      control: { type: 'select' },
      options: [InputSize.Large, InputSize.Medium, InputSize.Small, InputSize.Inline],
    },
    shape: {
      control: { type: 'select' },
      options: [InputShape.Rounded, InputShape.Pill],
    },
    floating: {
      control: 'boolean',
      default: false,
      if: { arg: 'size', neq: InputSize.Inline },
    },
    inputChange: { action: 'inputChange', table: { type: { summary: 'EventEmitter' } } },
    inputBlur: { action: 'inputBlur', table: { type: { summary: 'EventEmitter' } } },
  },
  render: ({ ...args }) => {
    const floating = args.floating === undefined ? false : args.floating;
    return `<kfds-input shape='${args.shape}' size='${args.size}' disabled='${args.disabled}' label='${args.label}' supporting-text='${args.supportingText}' placeholder='${args.placeHolder}' max-length='${args.maxLength}' custom-class='${args.customClass}' required='${args.required}' floating='${floating}' name='sampleinput'></kfds-input>`;
  },
  parameters: {
    docs: {
        source: { 
          code: `// React
import { KfdsInput } from '@kone-ds/webcomponents-react';
import { InputShape, InputSize } from '@kone-ds/webcomponents';

<KfdsInput
  name='input1'
  type='text'
  value='test'
  label='Sample Input'
  size={InputSize.Medium}
  shape={InputShape.Rounded}
  supporting-text='Supporting Text'
  max-length={10}
  required={true}
  onInputChange={(event) => console.log('input change', event)}
  onInputBlur={(event) => console.log('input blur', event)} />
`,
        },
      },
  }
};

export const LargeInput = {
  args: {
    label: 'Label',
    size: InputSize.Large,
    shape: InputShape.Rounded,
    disabled: false,
    supportingText: 'Supporting Text',
    placeHolder: 'Input Text',
    maxLength: 10,
    customClass: '',
    required: true,
    floating: false,
  },
};

export const MediumInput = {
  args: {
    label: 'Label',
    size: InputSize.Medium,
    shape: InputShape.Rounded,
    disabled: false,
    supportingText: 'Supporting Text',
    placeHolder: 'Input Text',
    maxLength: 10,
    customClass: 'error',
    required: true,
    floating: false,
  },
};

export const SmallInput = {
  args: {
    label: 'Label',
    size: InputSize.Small,
    shape: InputShape.Rounded,
    disabled: false,
    supportingText: 'Supporting Text',
    placeHolder: 'Input Text',
    customClass: '',
    required: true,
    floating: false,
  },
};

export const LargeFloatingInput = {
  args: {
    label: 'Label',
    shape: InputShape.Rounded,
    size: InputSize.Large,
    disabled: false,
    supportingText: 'Supporting Text',
    placeHolder: 'Input Text',
    customClass: '',
    required: true,
    floating: true,
  },
};
