import { Component, Host, h, Prop, State, Event, EventEmitter } from '@stencil/core';
import CloseCrossIcon from '@kone-ds/assets/dist/icons/close-cross.svg';
import { BannerType, BannerPosition } from './kfds-banner.enum';

@Component({
  tag: 'kfds-banner',
  styleUrl: 'kfds-banner.scss',
  shadow: true,
})
export class KfdsBanner {
  @Prop() type: BannerType = BannerType.Info;
  @Prop() position: BannerPosition = BannerPosition.Top;
  @Prop() elementId: string;
  @Prop() message: string;
  @Prop() customClass: string = '';
  @Prop() actions;

  @State() showBanner = true;

  @Event() actionLinkClicked: EventEmitter<string>;

  handleLinkClick(action) {
    this.actionLinkClicked.emit(action);
  }

  getIcon() {
    switch(this.type) {
      case BannerType.Info:
        return <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none">
        <path d="M1.5 12C1.5 17.799 6.20105 22.5 12 22.5C17.799 22.5 22.5 17.799 22.5 12C22.5 6.20105 17.799 1.5 12 1.5C6.20105 1.5 1.5 6.20105 1.5 12ZM11.1 17.9996V10.5H12.9V17.9996H11.1ZM12 8.70002C11.3373 8.70002 10.8 8.16276 10.8 7.50002C10.8 6.83728 11.3373 6.30002 12 6.30002C12.6628 6.30002 13.2 6.83728 13.2 7.50002C13.2 8.16276 12.6628 8.70002 12 8.70002Z" fill="#141414"/>
      </svg>
      case BannerType.Success:
        return <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none">
        <path d="M12 22.5C17.799 22.5 22.5 17.799 22.5 12C22.5 6.20101 17.799 1.5 12 1.5C6.20101 1.5 1.5 6.20101 1.5 12C1.5 17.799 6.20101 22.5 12 22.5ZM17.0304 9.53039L11.0304 15.5304C10.7375 15.8233 10.2626 15.8233 9.96973 15.5304L6.96973 12.5304L8.03039 11.4697L10.5001 13.9394L15.9697 8.46973L17.0304 9.53039Z" fill="#141414"/>
      </svg>      
      case BannerType.Warning:
        return <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none">
        <path d="M12 1.5C17.799 1.5 22.5 6.20105 22.5 12C22.5 17.799 17.799 22.5 12 22.5C6.20105 22.5 1.5 17.799 1.5 12C1.5 6.20105 6.20105 1.5 12 1.5ZM12.9 7.2H11.1V13.6904H12.9V7.2ZM11.1 15.3V17.1H12.9V15.3H11.1Z" fill="#141414"/>
      </svg>
      case BannerType.Error:
        return <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none">
        <path d="M22.2835 19.8562C22.4251 20.112 22.4997 20.4022 22.5 20.6975C22.5002 20.9929 22.4261 21.2832 22.2849 21.5392C22.1437 21.7953 21.9405 22.0082 21.6956 22.1566C21.4507 22.3049 21.1727 22.3836 20.8894 22.3846H3.11057C2.82734 22.3836 2.54934 22.3049 2.30443 22.1566C2.05952 22.0082 1.8563 21.7953 1.71511 21.5392C1.57393 21.2832 1.49975 20.9929 1.5 20.6975C1.50025 20.4022 1.57493 20.112 1.71654 19.8562L10.606 3.84306C10.7465 3.58693 10.9495 3.37406 11.1943 3.22601C11.4391 3.07797 11.717 3 12 3C12.283 3 12.5609 3.07797 12.8057 3.22601C13.0505 3.37406 13.2535 3.58693 13.394 3.84306L22.2835 19.8562ZM12.8401 15.9231V9.46158H11.1601V15.9231H12.8401ZM12.84 17.5385H11.16V19.2185H12.84V17.5385Z" fill="#141414"/>
      </svg>;            
    }
  }

  removeBanner() {
    this.showBanner = false;
  }

  render() {
    const actions = Array.isArray(this.actions) ? this.actions : (this.actions ? JSON.parse(this.actions) : []);
    return (
      <Host>
        {this.showBanner ?
          <div part='banner-container' id={this.elementId} class={this.type + ' kfds-banner-container ' + this.position + ' ' + this.customClass}>
            <span part='icon' class='icon'>{this.getIcon()}</span>
            <span part='message' class='message'>{this.message}</span>
            {actions.map((action, index) => 
              <kfds-hyperlink
              part='hyperlink' 
              key={index} 
              href={action.href}
              onLinkClicked={() => this.handleLinkClick(action)}
              element-id={action.elementId}
              target={action.target}>
                {action.label}
              </kfds-hyperlink>
            )}
            <a part='close' class='close' onClick={() => this.removeBanner()}><img src={CloseCrossIcon} /></a>
          </div>
        : null }
      </Host> 
    );
  }

}
