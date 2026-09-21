import { TestBed } from '@angular/core/testing';

import { KoneDsWebcomponentsAngularService } from './kone-ds-webcomponents-angular.service';

describe('KoneDsWebcomponentsAngularService', () => {
  let service: KoneDsWebcomponentsAngularService;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    service = TestBed.inject(KoneDsWebcomponentsAngularService);
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });
});
