// Functions と Web アプリが使うユーザー割り当てマネージド ID（Cosmos と Web PubSub の権限を先に付けられるよう、別に作る）
param location string
param tags object
param resourceToken string
@description('名前の接頭辞（func: Functions、web: Web アプリ）')
param prefix string = 'func'

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${prefix}-${resourceToken}'
  location: location
  tags: tags
}

output id string = identity.id
output clientId string = identity.properties.clientId
output principalId string = identity.properties.principalId
