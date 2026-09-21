/* tslint:disable */
/* auto-generated angular directive proxies */
import { ChangeDetectionStrategy, ChangeDetectorRef, Component, ElementRef, EventEmitter, NgZone } from '@angular/core';

import { ProxyCmp, proxyOutputs } from './angular-component-lib/utils';

import { Components } from '@kone-ds/webcomponents';


@ProxyCmp({
  inputs: ['actions', 'customClass', 'elementId', 'message', 'position', 'type']
})
@Component({
  selector: 'kfds-banner',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: '<ng-content></ng-content>',
  // eslint-disable-next-line @angular-eslint/no-inputs-metadata-property
  inputs: ['actions', 'customClass', 'elementId', 'message', 'position', 'type'],
})
export class KfdsBanner {
  protected el: HTMLElement;
  constructor(c: ChangeDetectorRef, r: ElementRef, protected z: NgZone) {
    c.detach();
    this.el = r.nativeElement;
    proxyOutputs(this, this.el, ['actionLinkClicked']);
  }
}


export declare interface KfdsBanner extends Components.KfdsBanner {

  actionLinkClicked: EventEmitter<CustomEvent<string>>;
}


@ProxyCmp({
  inputs: ['customClass', 'elementId', 'isTruncated', 'links', 'size', 'type']
})
@Component({
  selector: 'kfds-breadcrumb',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: '<ng-content></ng-content>',
  // eslint-disable-next-line @angular-eslint/no-inputs-metadata-property
  inputs: ['customClass', 'elementId', 'isTruncated', 'links', 'size', 'type'],
})
export class KfdsBreadcrumb {
  protected el: HTMLElement;
  constructor(c: ChangeDetectorRef, r: ElementRef, protected z: NgZone) {
    c.detach();
    this.el = r.nativeElement;
    proxyOutputs(this, this.el, ['itemClicked']);
  }
}


export declare interface KfdsBreadcrumb extends Components.KfdsBreadcrumb {

  itemClicked: EventEmitter<CustomEvent<string>>;
}


@ProxyCmp({
  inputs: ['buttonStyle', 'customClass', 'disabled', 'elementId', 'size', 'type']
})
@Component({
  selector: 'kfds-button',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: '<ng-content></ng-content>',
  // eslint-disable-next-line @angular-eslint/no-inputs-metadata-property
  inputs: ['buttonStyle', 'customClass', 'disabled', 'elementId', 'size', 'type'],
})
export class KfdsButton {
  protected el: HTMLElement;
  constructor(c: ChangeDetectorRef, r: ElementRef, protected z: NgZone) {
    c.detach();
    this.el = r.nativeElement;
    proxyOutputs(this, this.el, ['buttonClicked']);
  }
}


export declare interface KfdsButton extends Components.KfdsButton {

  buttonClicked: EventEmitter<CustomEvent<any>>;
}


@ProxyCmp({
  inputs: ['customClass', 'disabled', 'elementId', 'label', 'name', 'options', 'orientation', 'required', 'selectedOptions', 'size']
})
@Component({
  selector: 'kfds-checkbox',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: '<ng-content></ng-content>',
  // eslint-disable-next-line @angular-eslint/no-inputs-metadata-property
  inputs: ['customClass', 'disabled', 'elementId', 'label', 'name', 'options', 'orientation', 'required', 'selectedOptions', 'size'],
})
export class KfdsCheckbox {
  protected el: HTMLElement;
  constructor(c: ChangeDetectorRef, r: ElementRef, protected z: NgZone) {
    c.detach();
    this.el = r.nativeElement;
    proxyOutputs(this, this.el, ['checkboxClicked']);
  }
}


export declare interface KfdsCheckbox extends Components.KfdsCheckbox {

  checkboxClicked: EventEmitter<CustomEvent<string[]>>;
}


@ProxyCmp({
  inputs: ['customClass', 'elementId', 'href', 'target']
})
@Component({
  selector: 'kfds-hyperlink',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: '<ng-content></ng-content>',
  // eslint-disable-next-line @angular-eslint/no-inputs-metadata-property
  inputs: ['customClass', 'elementId', 'href', 'target'],
})
export class KfdsHyperlink {
  protected el: HTMLElement;
  constructor(c: ChangeDetectorRef, r: ElementRef, protected z: NgZone) {
    c.detach();
    this.el = r.nativeElement;
    proxyOutputs(this, this.el, ['linkClicked']);
  }
}


export declare interface KfdsHyperlink extends Components.KfdsHyperlink {

  linkClicked: EventEmitter<CustomEvent<any>>;
}


@ProxyCmp({
  inputs: ['customClass', 'disabled', 'elementId', 'floating', 'label', 'maxLength', 'name', 'placeholder', 'required', 'shape', 'size', 'supportingText', 'type', 'value']
})
@Component({
  selector: 'kfds-input',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: '<ng-content></ng-content>',
  // eslint-disable-next-line @angular-eslint/no-inputs-metadata-property
  inputs: ['customClass', 'disabled', 'elementId', 'floating', 'label', 'maxLength', 'name', 'placeholder', 'required', 'shape', 'size', 'supportingText', 'type', 'value'],
})
export class KfdsInput {
  protected el: HTMLElement;
  constructor(c: ChangeDetectorRef, r: ElementRef, protected z: NgZone) {
    c.detach();
    this.el = r.nativeElement;
    proxyOutputs(this, this.el, ['inputChange', 'inputBlur']);
  }
}


export declare interface KfdsInput extends Components.KfdsInput {

  inputChange: EventEmitter<CustomEvent<string>>;

  inputBlur: EventEmitter<CustomEvent<string>>;
}


@ProxyCmp({
  inputs: ['appName', 'customClass', 'elementId', 'now', 'progressBar', 'progressNum', 'restartButton', 'videoBackground']
})
@Component({
  selector: 'kfds-loader',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: '<ng-content></ng-content>',
  // eslint-disable-next-line @angular-eslint/no-inputs-metadata-property
  inputs: ['appName', 'customClass', 'elementId', 'now', 'progressBar', 'progressNum', 'restartButton', 'videoBackground'],
})
export class KfdsLoader {
  protected el: HTMLElement;
  constructor(c: ChangeDetectorRef, r: ElementRef, protected z: NgZone) {
    c.detach();
    this.el = r.nativeElement;
  }
}


export declare interface KfdsLoader extends Components.KfdsLoader {}


@ProxyCmp({
  inputs: ['actions', 'customClass', 'elementId', 'messageTitle', 'position', 'type']
})
@Component({
  selector: 'kfds-message',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: '<ng-content></ng-content>',
  // eslint-disable-next-line @angular-eslint/no-inputs-metadata-property
  inputs: ['actions', 'customClass', 'elementId', 'messageTitle', 'position', 'type'],
})
export class KfdsMessage {
  protected el: HTMLElement;
  constructor(c: ChangeDetectorRef, r: ElementRef, protected z: NgZone) {
    c.detach();
    this.el = r.nativeElement;
    proxyOutputs(this, this.el, ['actionButtonClicked']);
  }
}


export declare interface KfdsMessage extends Components.KfdsMessage {

  actionButtonClicked: EventEmitter<CustomEvent<string>>;
}


@ProxyCmp({
  inputs: ['actions', 'elementId', 'modalTitle', 'showIllustration', 'visible']
})
@Component({
  selector: 'kfds-modal',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: '<ng-content></ng-content>',
  // eslint-disable-next-line @angular-eslint/no-inputs-metadata-property
  inputs: ['actions', 'elementId', 'modalTitle', 'showIllustration', 'visible'],
})
export class KfdsModal {
  protected el: HTMLElement;
  constructor(c: ChangeDetectorRef, r: ElementRef, protected z: NgZone) {
    c.detach();
    this.el = r.nativeElement;
    proxyOutputs(this, this.el, ['actionButtonClicked']);
  }
}


export declare interface KfdsModal extends Components.KfdsModal {

  actionButtonClicked: EventEmitter<CustomEvent<string>>;
}


@ProxyCmp({
  inputs: ['customClass', 'disabled', 'elementId', 'label', 'name', 'options', 'orientation', 'required', 'selectedOption', 'size']
})
@Component({
  selector: 'kfds-radio',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: '<ng-content></ng-content>',
  // eslint-disable-next-line @angular-eslint/no-inputs-metadata-property
  inputs: ['customClass', 'disabled', 'elementId', 'label', 'name', 'options', 'orientation', 'required', 'selectedOption', 'size'],
})
export class KfdsRadio {
  protected el: HTMLElement;
  constructor(c: ChangeDetectorRef, r: ElementRef, protected z: NgZone) {
    c.detach();
    this.el = r.nativeElement;
    proxyOutputs(this, this.el, ['radioClicked']);
  }
}


export declare interface KfdsRadio extends Components.KfdsRadio {

  radioClicked: EventEmitter<CustomEvent<string>>;
}


@ProxyCmp({
  inputs: ['customClass', 'disabled', 'elementId', 'label', 'name', 'options', 'placeholder', 'required', 'selectedOption', 'shape', 'size', 'supportingText']
})
@Component({
  selector: 'kfds-select',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: '<ng-content></ng-content>',
  // eslint-disable-next-line @angular-eslint/no-inputs-metadata-property
  inputs: ['customClass', 'disabled', 'elementId', 'label', 'name', 'options', 'placeholder', 'required', 'selectedOption', 'shape', 'size', 'supportingText'],
})
export class KfdsSelect {
  protected el: HTMLElement;
  constructor(c: ChangeDetectorRef, r: ElementRef, protected z: NgZone) {
    c.detach();
    this.el = r.nativeElement;
    proxyOutputs(this, this.el, ['selectChange', 'selectBlur']);
  }
}


export declare interface KfdsSelect extends Components.KfdsSelect {

  selectChange: EventEmitter<CustomEvent<string>>;

  selectBlur: EventEmitter<CustomEvent<string>>;
}


@ProxyCmp({
  inputs: ['customClass', 'disabled', 'elementId', 'label', 'max', 'min', 'required', 'selectedValue', 'showLabel', 'showNumberInput', 'showSupportingText', 'sliderClass', 'supportingText', 'unit']
})
@Component({
  selector: 'kfds-slider',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: '<ng-content></ng-content>',
  // eslint-disable-next-line @angular-eslint/no-inputs-metadata-property
  inputs: ['customClass', 'disabled', 'elementId', 'label', 'max', 'min', 'required', 'selectedValue', 'showLabel', 'showNumberInput', 'showSupportingText', 'sliderClass', 'supportingText', 'unit'],
})
export class KfdsSlider {
  protected el: HTMLElement;
  constructor(c: ChangeDetectorRef, r: ElementRef, protected z: NgZone) {
    c.detach();
    this.el = r.nativeElement;
    proxyOutputs(this, this.el, ['inputChange', 'inputBlur']);
  }
}


export declare interface KfdsSlider extends Components.KfdsSlider {

  inputChange: EventEmitter<CustomEvent<string>>;

  inputBlur: EventEmitter<CustomEvent<string>>;
}


@ProxyCmp({
  inputs: ['actions', 'autoHide', 'customClass', 'duration', 'elementId', 'horizontalPosition', 'message', 'showClose', 'type', 'verticalPosition', 'visible']
})
@Component({
  selector: 'kfds-snackbar',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: '<ng-content></ng-content>',
  // eslint-disable-next-line @angular-eslint/no-inputs-metadata-property
  inputs: ['actions', 'autoHide', 'customClass', 'duration', 'elementId', 'horizontalPosition', 'message', 'showClose', 'type', 'verticalPosition', 'visible'],
})
export class KfdsSnackbar {
  protected el: HTMLElement;
  constructor(c: ChangeDetectorRef, r: ElementRef, protected z: NgZone) {
    c.detach();
    this.el = r.nativeElement;
    proxyOutputs(this, this.el, ['actionLinkClicked']);
  }
}


export declare interface KfdsSnackbar extends Components.KfdsSnackbar {

  actionLinkClicked: EventEmitter<CustomEvent<string>>;
}


@ProxyCmp({
  inputs: ['customClass', 'elementId', 'position', 'text', 'tooltipStyle']
})
@Component({
  selector: 'kfds-tooltip',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: '<ng-content></ng-content>',
  // eslint-disable-next-line @angular-eslint/no-inputs-metadata-property
  inputs: ['customClass', 'elementId', 'position', 'text', 'tooltipStyle'],
})
export class KfdsTooltip {
  protected el: HTMLElement;
  constructor(c: ChangeDetectorRef, r: ElementRef, protected z: NgZone) {
    c.detach();
    this.el = r.nativeElement;
  }
}


export declare interface KfdsTooltip extends Components.KfdsTooltip {}


