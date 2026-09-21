import { Component, Prop, h } from '@stencil/core';
import { TooltipPosition, TooltipStyle } from './kfds-tooltip.enum';

@Component({
  tag: 'kfds-tooltip',
  styleUrl: 'kfds-tooltip.scss',
  shadow: true,
})
export class KfdsTooltip {
  @Prop() position: TooltipPosition = TooltipPosition.Top;
  @Prop() elementId: string;
  @Prop() customClass: string = '';
  @Prop() tooltipStyle: TooltipStyle = TooltipStyle.Primary;
  @Prop() text = '';

  render() {
    return (
      <div part='tooltip' id={this.elementId} class={`kfds-tooltip ${this.tooltipStyle} ${this.position} ${this.customClass}`} data-tooltip={this.text}>
        <slot />
      </div>
    );
  }
}
