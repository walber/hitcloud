
Como um especialista em serviços da AWS, eu gostaria que você fornesse sugestões de arquitetura (incluindo diagrama(s)) para o seguinte senário:

## Senário:

Uma startup de marketing está lançando uma campanha para um novo produto. Eles criaram uma página de "Em Breve" e precisam de um contador simples que mostre
quantas pessoas já se interessaram. Como eles não sabem se terão 10 ou 1 milhão de acessos, eles querem uma solução Serverless (sem servidor), que seja barata e escale automaticamente.

Crie um **diagrama técnico profissional de arquitetura AWS**, com aparência semelhante aos diagramas oficiais usados em documentação técnica, apresentações de arquitetura de soluções e AWS Well-Architected reviews.

---

## OBJETIVO VISUAL

A imagem deve representar uma arquitetura AWS de maneira:

* tecnicamente clara;
* profissional;
* limpa;
* organizada;
* facilmente compreensível em uma apresentação;
* visualmente semelhante a um diagrama de arquitetura AWS;
* sem aparência artística, ilustrativa ou futurista.

Priorize **clareza técnica e legibilidade**, não decoração.

---

## ESTILO GRÁFICO

Use:

* estilo de **diagrama vetorial 2D**;
* visão frontal;
* sem perspectiva 3D;
* sem isometria;
* sem sombras excessivas;
* sem efeitos de profundidade;
* sem objetos realistas;
* sem elementos decorativos desnecessários;
* fundo branco ou extremamente claro;
* linhas finas, nítidas e bem definidas;
* alta nitidez;
* ícones visualmente consistentes com o padrão de **AWS Architecture Icons**;
* tipografia simples, técnica e legível.

A imagem deve parecer criada em uma ferramenta profissional de diagramas de arquitetura, como Draw.io, Lucidchart ou documentação de arquitetura AWS.

---

## QUALIDADE DA IMAGEM

A imagem deve ser:

* extremamente nítida;
* em alta resolução;
* sem blur;
* sem distorção;
* sem objetos cortados;
* sem ícones deformados;
* sem texto sobreposto;
* sem texto borrado;
* sem setas atravessando ícones;
* sem componentes desalinhados;
* sem elementos flutuando aleatoriamente.

Todos os componentes devem permanecer totalmente dentro da área da imagem.

Manter **margens externas generosas**.

---

## FORMATO

Criar em formato horizontal.

Aspect ratio preferencial:

**16:9**

O diagrama deve funcionar bem dentro de um slide de apresentação PowerPoint.

Centralizar visualmente a arquitetura e distribuir os elementos para aproveitar o espaço horizontal.

---

## HIERARQUIA DA ARQUITETURA

Representar claramente os limites lógicos da infraestrutura.

Quando aplicável, utilizar containers ou caixas delimitadoras para:

1. Internet / Usuários Externos
2. AWS Cloud
3. Região AWS
4. VPC
5. Zonas de Disponibilidade
6. Camada de Dados
7. Camada de Segurança
8. Monitoramento / Observabilidade

A hierarquia deve ser imediatamente compreensível visualmente.

---

## REGIÃO AWS

Criar uma grande caixa externa identificando:

**AWS Region: us-west-2**

Dentro dela, inserir apenas os recursos que efetivamente pertencem à região.

Serviços globais devem aparecer fora da caixa da região quando tecnicamente apropriado.

---

## VPC

Quando aplicável, criar um container identificado como:

**Amazon VPC**

Dentro da VPC, organizar corretamente:

* Availability Zones;
* public subnets;
* private subnets;
* componentes de aplicação;
* componentes de dados.

Não colocar dentro da VPC serviços AWS que normalmente são serviços regionais gerenciados e não pertencem diretamente a uma subnet, salvo quando a representação exigir endpoints ou componentes específicos.

---

## AVAILABILITY ZONES

Se a arquitetura utilizar alta disponibilidade, representar claramente:

**us-west-2a**

e

**us-west-2b**

lado a lado.

Nos recursos Multi-AZ, deixar isso visualmente evidente.

Não criar a falsa impressão de que serviços AWS regionais pertencem exclusivamente a uma única Availability Zone.

---

## ORGANIZAÇÃO VISUAL

Usar fluxo principal:

**esquerda → direita**

Sempre que possível:

Users / Internet
→ DNS / Edge / Security
→ API Layer
→ Compute
→ Database

Serviços auxiliares podem ficar acima ou abaixo do fluxo principal.

Exemplo:

* Security: parte superior;
* Observability: parte inferior;
* Messaging / Integration: próximo da camada de aplicação;
* Data / Analytics: próximo da camada de dados.

Evitar cruzamento de linhas.

Evitar linhas diagonais quando linhas horizontais ou verticais forem suficientes.

---

## CONEXÕES

Representar conexões usando setas simples e profissionais.

Usar:

* setas direcionais para fluxo de requisições;
* linhas simples quando apenas uma associação estiver sendo mostrada;
* poucas setas;
* caminhos claros.

Não criar uma rede excessivamente complexa de linhas.

Quando vários serviços se comunicarem com um mesmo componente, organizar os elementos para reduzir cruzamentos.

---

## ÍCONES AWS

Utilizar ícones reconhecíveis e consistentes com os serviços AWS especificados.

Não:

* inventar serviços;
* substituir serviços AWS por ícones genéricos;
* criar logos inexistentes;
* duplicar recursos sem necessidade;
* alterar o significado dos serviços.

Cada serviço deve aparecer **uma única vez**, exceto quando a arquitetura exigir explicitamente múltiplas instâncias ou componentes por Availability Zone.

---

## NOMES DOS SERVIÇOS

Mostrar o nome técnico correto abaixo ou ao lado do ícone.

Exemplos:

Amazon CloudFront
AWS WAF
Amazon Route 53
AWS Lambda
Amazon DynamoDB
Amazon S3
Amazon CloudWatch
AWS Shield Standard

Evitar textos longos.

Usar somente rótulos técnicos essenciais.

---

## TEXTO

Minimizar texto dentro da imagem.

Não adicionar:

* parágrafos;
* explicações extensas;
* bullets;
* descrições comerciais;
* vantagens do serviço;
* informações não solicitadas.

A imagem deve comunicar principalmente através da **estrutura e dos serviços**.

---

## FIDELIDADE TÉCNICA

Muito importante:

A posição dos componentes deve respeitar a arquitetura real da AWS.

Não representar incorretamente:

* serviços regionais como pertencentes a uma única AZ;
* serviços globais dentro de uma subnet;
* CloudFront dentro da VPC;
* Route 53 dentro da VPC;
* AWS Shield como uma instância ou appliance;
* CloudWatch dentro de uma Availability Zone;
* S3 como servidor EC2;
* serviços serverless como servidores físicos.

Se determinado serviço operar em nível regional, representar isso visualmente de maneira coerente.

Se for Multi-AZ por natureza ou por configuração, não associá-lo visualmente a apenas uma AZ sem motivo técnico.

---

## ALTA DISPONIBILIDADE

Quando aplicável, destacar de maneira discreta:

**Multi-AZ**

Mostrar a redundância através da própria estrutura do diagrama, e não através de grandes blocos de texto.

A arquitetura deve deixar claro quais componentes possuem redundância entre Availability Zones.

---

## SEGURANÇA

Quando houver componentes de segurança, posicioná-los de forma tecnicamente correta.

Exemplos:

AWS Shield
AWS WAF
IAM
AWS KMS
Secrets Manager
Security Groups

Evitar representar serviços de segurança como se fossem firewalls físicos instalados dentro da rede, quando isso não corresponder ao funcionamento real do serviço.

---

## OBSERVABILIDADE

Quando solicitado, criar uma pequena área visual para observabilidade contendo os serviços apropriados, por exemplo:

Amazon CloudWatch
AWS CloudTrail

Essa área deve estar relacionada à arquitetura sem dominar o diagrama.

---

## ARQUITETURA A SER REPRESENTADA

Usar EXCLUSIVAMENTE os componentes descritos abaixo.

### Entrada / Usuários

Site estático no S3.

### Edge / DNS / Proteção

Route 53

### Network

API Gateway

### Compute

AWS Lambda

### Database

DynamoDB

### Mensagens de Email

Amazon SES

## Enfileiramento de Mensagens

Amazon SQS e SQS DLQ 

### Security

WAF e AWS Shield Standard

### Monitoring / Observability

Amazon CloudWatch

---

## REGRAS ESPECÍFICAS DE POSICIONAMENTO

* Amazon API Gateway: A porta de entrada que recebe o clique do usuário.
* S3: Deve hopedar um site estático com uma página que exibe a contagem de acessos.
* Amazon CloudFront: Fornece o conteúdo do site estático com baixa latência.
* AWS Lambda: O "cérebro" (uma função que só roda quando é chamada) que recebe o aviso do API Gateway e soma +1 no banco de dados.
* Amazon DynamoDB: Um banco de dados super rápido onde guardaremos o número total de acessos.
* Permissões (IAM): Verificar se as permissões entre os serviços estão corretas. O Lambda deve ter a permissão de ler e escrever (PutItem/UpdateItem) na tabela do DynamoDB. Por padrão, nada no AWS conversa com nada.
* Partição de Dados: No DynamoDB, você precisa de uma Partition Key. Para um contador simples, você pode usar uma chave fixa como "id": "hits".
* A infraestrutura deve aparecer nas duas Availability Zones.
* CloudWatch deve ficar fora das Availability Zones, conectado conceitualmente aos recursos monitorados.

## MELHORIAS FUTURAS

* AWS Lambda: validar os dados e enviar o cadastro para a fila (gravar os emails cadastros, tratando repetições e falhas).
* DynamoDB: utilizar a criptorafia em repouso do DynamoDB para amazenar os emails inscritos.
* Amazon SES: enviar um email de confirmação.
* IAM: com privilégio mínimo, a função Lambda de entrada só envia à fila; a processadora acessa somente a fila e a tabela necessárias. O navegador não recebe credenciais de acesso ao banco.
* SQS Standard: para a fila de cadastros. Absorver picos e desacoplar o recebimento da gravação.
* SQS DLQ: fila de mensagens com falhas persistentes para permitir a investigação e reprocessamento.
* Amazon SES: para o envio de confirmação de email.

---

## RESTRIÇÕES

Não incluir nenhum serviço que não tenha sido solicitado.

Não alterar a arquitetura.

Não simplificar removendo componentes importantes.

Não criar componentes adicionais para preencher espaço.

Não duplicar serviços sem justificativa.

Não adicionar legendas extensas.

Não adicionar título gigante.

Não usar imagens fotorealistas.

Não usar aparência de data center físico.

Não usar estética cyberpunk, neon, holográfica ou futurista.

Não usar perspectiva 3D.

Não usar ícones genéricos quando existir um ícone AWS correspondente.

---

## RESULTADO ESPERADO

Gerar **dois diagramas de arquitetura AWS (separadamente)**, um com todos os serviços e outro sem os serviços inseridos na seção de melhorias futuras, horizontal, 16:9, limpo, profissional, tecnicamente coerente e adequado para apresentação técnica.

Prioridades, nesta ordem:

1. Correção da arquitetura
2. Legibilidade
3. Organização espacial
4. Fidelidade dos serviços AWS
5. Nitidez
6. Estética profissional

Antes de compor visualmente o diagrama, interpretar a arquitetura como um **diagrama técnico de infraestrutura**, e não como uma ilustração artística.

---

## VALIDAÇÃO VISUAL OBRIGATÓRIA

Manter pelo menos:
- 24 px de espaço interno nos blocos;
- 40 px entre blocos;
- 12 px entre textos e linhas;
- 60 px entre o conteúdo e as bordas externas.

Essas medidas devem ser consideradas em uma composição
base de 1920 × 1080 e escaladas proporcionalmente na exportação.

Antes de entregar:
- conferir todas as conexões, do início ao fim;
- verificar se cada seta aponta inequivocamente para seu destino;
- verificar se todos os textos cabem em seus blocos;
- verificar se nenhum componente ultrapassa seu container;
- conferir especialmente a área de SQS, DLQ, processamento e CloudWatch;
- revisar a imagem inteira em 1920 × 1080 para avaliar legibilidade.

Se houver conflito de espaço, reorganizar os componentes
ou encurtar os rótulos antes de reduzir a tipografia.

Exportar a versão final em 8K, mantendo exatamente
o enquadramento e a proporção 16:9 da composição validada.