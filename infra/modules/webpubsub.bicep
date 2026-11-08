// 画面への再読み込みの合図に使う。Free 枠、キーでの接続は無効
param location string
param tags object
param resourceToken string
param ownerPrincipalId string

var hub = 'proactive'

resource webPubSub 'Microsoft.SignalRService/webPubSub@2024-03-01' = {
  name: 'wps-${resourceToken}'
  location: location
  tags: tags
  sku: { name: 'Free_F1', capacity: 1 }
  properties: {
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

// 12cf5a90-567b-43ae-8102-96cf46c7d9b4 = Web PubSub Service Owner
resource owner 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: webPubSub
  name: guid(webPubSub.id, ownerPrincipalId, 'webpubsub-owner')
  properties: {
    principalId: ownerPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '12cf5a90-567b-43ae-8102-96cf46c7d9b4')
  }
}

output endpoint string = 'https://${webPubSub.properties.hostName}'
output hub string = hub
