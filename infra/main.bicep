// proactive-agent の基盤一式（Plan 2）。azd up で作る。
targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('azd の環境名')
param environmentName string

@minLength(1)
@description('地域。japaneast を想定（README の「地域」）')
param location string

@description('デプロイする人の object ID。シード投入のために Cosmos のデータ権限を付ける')
param principalId string = ''

var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var tags = { 'azd-env-name': environmentName }

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module monitoring 'modules/monitoring.bicep' = {
  scope: rg
  name: 'monitoring'
  params: { location: location, tags: tags, resourceToken: resourceToken }
}

module storage 'modules/storage.bicep' = {
  scope: rg
  name: 'storage'
  params: { location: location, tags: tags, resourceToken: resourceToken, deployerPrincipalId: principalId }
}

module identity 'modules/identity.bicep' = {
  scope: rg
  name: 'identity'
  params: { location: location, tags: tags, resourceToken: resourceToken }
}

module cosmos 'modules/cosmos.bicep' = {
  scope: rg
  name: 'cosmos'
  params: {
    location: location
    tags: tags
    resourceToken: resourceToken
    dataContributorPrincipalIds: empty(principalId)
      ? [identity.outputs.principalId]
      : [identity.outputs.principalId, principalId]
  }
}

module webPubSub 'modules/webpubsub.bicep' = {
  scope: rg
  name: 'webpubsub'
  params: {
    location: location
    tags: tags
    resourceToken: resourceToken
    ownerPrincipalId: identity.outputs.principalId
  }
}

module gatewayApp 'modules/gateway-app.bicep' = {
  scope: rg
  name: 'gateway-app'
  params: { environmentName: environmentName, resourceToken: resourceToken }
}

module functions 'modules/functions.bicep' = {
  scope: rg
  name: 'functions'
  params: {
    location: location
    tags: tags
    resourceToken: resourceToken
    identityId: identity.outputs.id
    identityClientId: identity.outputs.clientId
    identityPrincipalId: identity.outputs.principalId
    storageAccountName: storage.outputs.name
    deploymentContainerUrl: storage.outputs.deploymentContainerUrl
    appInsightsName: monitoring.outputs.appInsightsName
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
    cosmosEndpoint: cosmos.outputs.endpoint
    cosmosDatabase: cosmos.outputs.databaseName
    webPubSubEndpoint: webPubSub.outputs.endpoint
    webPubSubHub: webPubSub.outputs.hub
    gatewayTenantId: tenant().tenantId
    gatewayAudiences: '${gatewayApp.outputs.appId},${gatewayApp.outputs.identifierUri}'
  }
}

output AZURE_LOCATION string = location
output AZURE_TENANT_ID string = tenant().tenantId
output AZURE_RESOURCE_GROUP string = rg.name
output COSMOS_ENDPOINT string = cosmos.outputs.endpoint
output COSMOS_DATABASE string = cosmos.outputs.databaseName
output FUNCTION_APP_NAME string = functions.outputs.name
output FUNCTION_APP_URL string = functions.outputs.url
output WEBPUBSUB_ENDPOINT string = webPubSub.outputs.endpoint
output WEBPUBSUB_HUB string = webPubSub.outputs.hub
output GATEWAY_APP_ID string = gatewayApp.outputs.appId
output GATEWAY_APP_ID_URI string = gatewayApp.outputs.identifierUri
output AZURE_STORAGE_BLOB_ENDPOINT string = storage.outputs.blobEndpoint
output APPLICATIONINSIGHTS_CONNECTION_STRING string = monitoring.outputs.appInsightsConnectionString
