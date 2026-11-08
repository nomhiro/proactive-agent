// Functions が使うユーザー割り当てマネージド ID（Cosmos と Web PubSub の権限を先に付けられるよう、別に作る）
param location string
param tags object
param resourceToken string

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-func-${resourceToken}'
  location: location
  tags: tags
}

output id string = identity.id
output clientId string = identity.properties.clientId
output principalId string = identity.properties.principalId
