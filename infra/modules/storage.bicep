// Functions の実行とデプロイ用、HILS のログと解析のグラフ用。共有キーは使わない
param location string
param tags object
@minLength(3)
param resourceToken string

resource account 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'st${resourceToken}'
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    allowSharedKeyAccess: false
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource blob 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: account
  name: 'default'
}

resource containers 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = [
  for name in ['app-package', 'hils-logs', 'analysis-artifacts']: {
    parent: blob
    name: name
  }
]

output name string = account.name
output blobEndpoint string = account.properties.primaryEndpoints.blob
output deploymentContainerUrl string = '${account.properties.primaryEndpoints.blob}app-package'
