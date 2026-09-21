import { Component, Host, h, Prop, Fragment, Event, EventEmitter } from '@stencil/core';
import { BreadcrumbSize, BreadcrumbType } from './kfds-breadcrumb.enum';

@Component({
  tag: 'kfds-breadcrumb',
  styleUrl: 'kfds-breadcrumb.scss',
  shadow: true,
})
export class KfdsBreadcrumb {
  @Prop() links;
  @Prop() elementId: string;
  @Prop() isTruncated: boolean = false;
  @Prop() customClass: string = '';
  @Prop() size: string = BreadcrumbSize.Medium;
  @Prop() type: string = BreadcrumbType.Default;

  @Event() itemClicked: EventEmitter<string>;
  showExpanded() {
    this.isTruncated = false;
  }

  handleItemClick(link: any) {
    this.itemClicked.emit(link);
  }

  render() {
    const links = Array.isArray(this.links) ? this.links : (this.links ? JSON.parse(this.links) : []);
    const length = links.length;
    return (
      <Host>        
          {length > 0 && 
            <div part='breadcrumb-container' id={this.elementId} class={'kfds-breadcrumb-container ' + this.customClass + ' ' + this.type}>
              <div part='breadcrumb-container-inner' class={'kfds-breadcrumb-container-inner ' + ' ' + this.size}>
                {!this.isTruncated ? 
                  <Fragment>
                    {links.map((link, index) => 
                        <Fragment>
                          {(length -1 === index) ? 
                            <span part='breadcrumb-item-last' id={'kfds-breadcrumb-item-' + index}>{link.label}</span>
                            :
                            <a part='breadcrumb-item' onClick={() => this.handleItemClick(link)} class='kfds-breadcrumb-item' id={'kfds-breadcrumb-item-' + index}>{link.label}</a>
                          }
                          {(length -1 !== index) &&
                            <svg part='svg' width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                              <path fill-rule="evenodd" clip-rule="evenodd" d="M5.00001 3.90026L5.84338 3.08252L10.2596 7.36459C10.6648 7.75746 10.6648 8.40758 10.2596 8.80045L5.84338 13.0825L5.00001 12.2648L9.31329 8.08252L5.00001 3.90026Z" fill="#141414"/>
                            </svg>
                          }
                        </Fragment>
                    )}
                  </Fragment>
                  :
                  <Fragment>
                    <a part='breadcrumb-item' class='kfds-breadcrumb-item' id='kfds-breadcrumb-item-0' onClick={() => this.handleItemClick(links[0])}>{links[0].label}</a>
                    <svg part='svg' width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                      <path fill-rule="evenodd" clip-rule="evenodd" d="M5.00001 3.90026L5.84338 3.08252L10.2596 7.36459C10.6648 7.75746 10.6648 8.40758 10.2596 8.80045L5.84338 13.0825L5.00001 12.2648L9.31329 8.08252L5.00001 3.90026Z" fill="#141414"/>
                    </svg>
                    <a part='breadcrumb-item-expanded' class='kfds-breadcrumb-item' id='kfds-breadcrumb-item-1' onClick={() => this.showExpanded()}>...</a>
                    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                      <path fill-rule="evenodd" clip-rule="evenodd" d="M5.00001 3.90026L5.84338 3.08252L10.2596 7.36459C10.6648 7.75746 10.6648 8.40758 10.2596 8.80045L5.84338 13.0825L5.00001 12.2648L9.31329 8.08252L5.00001 3.90026Z" fill="#141414"/>
                    </svg>
                    <span part='breadcrumb-item-2' id='kfds-breadcrumb-item-2'>{links[length - 1].label}</span>
                  </Fragment>
                }
              </div>
            </div>
          }        
      </Host>
    );
  }

}
