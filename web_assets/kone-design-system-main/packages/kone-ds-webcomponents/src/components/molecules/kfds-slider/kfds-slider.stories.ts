export default {
  title: 'Components/Slider',
  tags: ['autodocs'],
  argTypes: {
    inputChange: { action: 'inputChange', table: { type: { summary: 'EventEmitter' } } },
    inputBlur: { action: 'inputBlur', table: { type: { summary: 'EventEmitter' } } },
  },
  render: ({ ...args }) => {
    return `<kfds-slider
    element-id='${args.elementId}'
    min='${args.min}'
    max='${args.max}'
    selected-value='${args.selectedValue}'
    disabled='${args.disabled}'
    label='${args.label}'
    show-label='${args.showLabel}'
    unit='${args.unit}'
    supporting-text='${args.supportingText}'
    required='${args.required}'
    show-number-input = '${args.showNumberInput}'
    show-supporting-text = '${args.showSupportingText}'
    custom-class = '${args.customClass}'
  ></kfds-slider>`;
  },
  parameters: {
    docs: {
        source: { 
          code: `// React
import { KfdsSlider } from '@kone-ds/webcomponents-react';

<KfdsSlider
  min={0}
  max={100}
  selected-value={20}
  label='Slider Label'
  show-number-input={true}
  show-supporting-text={true}
  supporting-text='Supporting Text'
/>
`,
        },
      },
}
};

export const FullSlider = {
  args: {
    elementId: 'exampleSlider',
    min: 0,
    max: 100,
    selectedValue: 50,
    disabled: false,
    label: 'Slider Label',
    showLabel: true,
    unit: '°C',
    supportingText: 'Please input an integer only.',
    required: false,
    showNumberInput: true,
    showSupportingText: true,
    customClass: '',
  },
};

export const DisabledSlider = {
  args: {
    elementId: 'exampleSlider',
    min: 0,
    max: 100,
    selectedValue: 50,
    disabled: true,
    label: 'Slider Label',
    showLabel: true,
    unit: '°C',
    supportingText: 'Please input an integer only.',
    required: false,
    showNumberInput: true,
    showSupportingText: true,
    customClass: '',
  },
};
