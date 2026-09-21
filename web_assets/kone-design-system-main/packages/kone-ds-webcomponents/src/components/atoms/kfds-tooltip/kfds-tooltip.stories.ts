import { TooltipPosition, TooltipStyle } from './kfds-tooltip.enum';

export default {
  // this creates a ‘Components’ folder and a Tooltip subfolder
  title: 'Components/Tooltip',
  tags: ['autodocs'],
  argTypes: {
    position: {
      control: { type: 'select' },
      options: [TooltipPosition.Top, TooltipPosition.Bottom, TooltipPosition.Left, TooltipPosition.Right],
    },
    style: {
      control: { type: 'select' },
      options: [TooltipStyle.Primary, TooltipStyle.Secondary],
    },
  },
  render: ({ ...args }) => {
    return `<kfds-tooltip position='${args.position}' tooltip-style='${args.style}' text='${args.text}'>
    <span>Hover Me!</span>
    </kfds-tooltip>`;
  },
  parameters: {
    docs: {
        source: { 
          code: `// React
import { KfdsTooltip } from '@kone-ds/webcomponents-react';
import { TooltipPosition, TooltipStyle } from '@kone-ds/webcomponents';

<KfdsTooltip 
  element-id='tooltip-1' 
  position={TooltipPosition.Top}
  tooltip-style={TooltipStyle.Primary}
  text='Tooltip Text'
>
  Sample Tooltip
</KfdsTooltip>
`,
        },
      },
}
};

export const topTooltip = {
  args: {
    text: 'Tooltip text',
    position: TooltipPosition.Top,
    style: TooltipStyle.Primary,
  },
};

export const bottomTooltip = {
  args: {
    text: 'Tooltip text',
    position: TooltipPosition.Bottom,
    style: TooltipStyle.Primary,
  },
};

export const leftTooltip = {
  args: {
    text: 'Tooltip text',
    position: TooltipPosition.Left,
    style: TooltipStyle.Primary,
  },
};

export const rightTooltip = {
  args: {
    text: 'Tooltip text',
    position: TooltipPosition.Right,
    style: TooltipStyle.Primary,
  },
};
