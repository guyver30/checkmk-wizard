import { Component, h, Prop, Event, EventEmitter } from '@stencil/core';

@Component({
  tag: 'kfds-hyperlink',
  styleUrl: 'kfds-hyperlink.scss',
  shadow: true,
})
export class KfdsHyperlink {
  @Prop() href: string;
  @Prop() target;
  @Prop() elementId: string;
  @Prop() customClass: string;

  @Event() linkClicked: EventEmitter;

  render() {
    return (
      <a part='hyperlink' onClick={() => this.emitClickEvent()} href={this.href} id={this.elementId} target={this.target} class={this.customClass}>
        <slot/>
      </a>
    );
  }

  emitClickEvent() {
    this.linkClicked.emit({
      href: this.href,
      elementId: this.elementId,
      customClass: this.customClass,
    });
  }

}
